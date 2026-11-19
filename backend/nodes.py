"""Node health and fallback.

Each job (vision, docs, coder, audio, sandbox) has a configured node in config.yaml `routing`.
`run_job` tries that node if it is healthy and falls back to the M5 on any error or timeout,
so a WIN failure never fails a request. Health is cached for `health.interval_s` and refreshed
either by the API's background loop or lazily on first use (pipeline scripts).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

from backend.config import get_config

log = logging.getLogger("benchlog.nodes")
T = TypeVar("T")

# Which endpoint of a node each job needs: an Ollama server or the WIN FastAPI service.
JOB_TARGET = {"vision": "ollama", "docs": "ollama", "coder": "ollama", "audio": "service", "sandbox": "service"}
LOCAL = "m5"

_lock = threading.Lock()
_status: dict[str, dict[str, Any]] = {}  # "win.service" -> {"up": bool, "checked": ts, "error": str|None}


def node_url(node: str, target: str) -> str | None:
    url = get_config()["nodes"].get(node, {}).get(target)
    if not url or "WIN_IP" in url:
        return None
    return url.rstrip("/")


def _probe(node: str, target: str) -> dict[str, Any]:
    url = node_url(node, target)
    now = time.time()
    if url is None:
        return {"up": False, "checked": now, "error": "not configured", "url": None}
    timeout = get_config()["health"]["timeout_s"]
    try:
        if target == "ollama":
            r = httpx.get(f"{url}/api/tags", timeout=timeout)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            return {"up": True, "checked": now, "error": None, "url": url, "models": models}
        r = httpx.get(f"{url}/health", timeout=timeout)
        r.raise_for_status()
        ok = r.json().get("ok") is True
        return {"up": ok, "checked": now, "error": None if ok else "service not ready", "url": url}
    except Exception as exc:  # noqa: BLE001 - any failure means "down"
        return {"up": False, "checked": now, "error": f"{type(exc).__name__}: {exc}"[:200], "url": url}


def refresh(node: str | None = None) -> dict[str, dict[str, Any]]:
    """Probe every (node, target) pair, or just one node's."""
    for n, targets in get_config()["nodes"].items():
        if node and n != node:
            continue
        for target in targets:
            st = _probe(n, target)
            key = f"{n}.{target}"
            with _lock:
                prev = _status.get(key)
                _status[key] = st
            _note_change(key, prev, st)
    with _lock:
        return dict(_status)


def _note_change(key: str, prev: dict[str, Any] | None, st: dict[str, Any]) -> None:
    """Log when a configured node goes up or down (the first probe counts as a change)."""
    if st.get("error") == "not configured":
        return
    if prev is not None and bool(prev.get("up")) == bool(st["up"]):
        return
    from backend import events

    state = "up" if st["up"] else "down"
    (log.info if st["up"] else log.warning)("node %s is %s %s", key, state, st.get("error") or "")
    events.record("node_" + state, node=key, url=st.get("url"), error=st.get("error"))


def is_up(node: str, target: str) -> bool:
    key = f"{node}.{target}"
    with _lock:
        st = _status.get(key)
    if st is None or time.time() - st["checked"] > get_config()["health"]["interval_s"] * 2:
        st = _probe(node, target)
        with _lock:
            _status[key] = st
    return bool(st["up"])


def mark_down(node: str, target: str, error: str) -> None:
    key = f"{node}.{target}"
    st = {"up": False, "checked": time.time(), "error": error[:200], "url": node_url(node, target)}
    with _lock:
        prev = _status.get(key)
        _status[key] = st
    _note_change(key, prev, st)


def route(job: str) -> str:
    """The node that should serve `job` right now: the configured one if healthy, else m5."""
    node = get_config()["routing"].get(job, LOCAL)
    if node != LOCAL and not is_up(node, JOB_TARGET[job]):
        return LOCAL
    return node


def run_job(job: str, remote: Callable[[str], T], local: Callable[[], T]) -> tuple[T, str, dict[str, Any]]:
    """Run `remote(node)` on the routed node, or `local()` on the M5.

    Returns (result, node_label, meta). meta has latency_s and, after a fallback, the error.
    """
    node = route(job)
    meta: dict[str, Any] = {"job": job}
    if node != LOCAL:
        t0 = time.time()
        try:
            result = remote(node)
            meta["latency_s"] = round(time.time() - t0, 2)
            log.info("job=%s node=%s latency=%.2fs", job, node.upper(), meta["latency_s"])
            return result, node.upper(), meta
        except Exception as exc:  # noqa: BLE001 - never let a remote node fail the request
            err = f"{type(exc).__name__}: {exc}"
            log.warning("job=%s node=%s failed (%s); falling back to M5", job, node.upper(), err[:200])
            mark_down(node, JOB_TARGET[job], err)
            meta["fallback_from"] = node.upper()
            meta["fallback_error"] = err[:300]
    t0 = time.time()
    result = local()
    meta["latency_s"] = round(time.time() - t0, 2)
    log.info("job=%s node=M5 latency=%.2fs", job, meta["latency_s"])
    return result, "M5", meta


def status() -> dict[str, Any]:
    """Health of every node plus which node serves each job right now."""
    with _lock:
        snap = dict(_status)
    cfg = get_config()
    expected = {f"{n}.{t}" for n, ts in cfg["nodes"].items() for t in ts}
    if not expected <= set(snap):  # nothing probed yet (first call before the health loop ran)
        snap = refresh()
    jobs = {}
    for job, configured in cfg["routing"].items():
        target = JOB_TARGET[job]
        up = snap.get(f"{configured}.{target}", {}).get("up", False)
        jobs[job] = {
            "configured": configured.upper(),
            "serving": (configured if (configured == LOCAL or up) else LOCAL).upper(),
            "model": _job_model(job),
        }
    return {"nodes": snap, "jobs": jobs}


def _job_model(job: str) -> str:
    m = get_config()["models"]
    return {
        "vision": m["vision"],
        "docs": f"{m['text']} + {m['embed']}",
        "coder": m["coder"],
        "audio": f"Whisper large-v3-turbo + AST ({m['sound']})",
        "sandbox": "Python subprocess, no network",
    }[job]


# ---------------------------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------------------------
_clients: dict[str, Any] = {}


def ollama_client(node: str = LOCAL):
    import ollama

    url = node_url(node, "ollama")
    if url is None:
        raise RuntimeError(f"node {node} has no Ollama URL configured")
    if url not in _clients:
        _clients[url] = ollama.Client(host=url, timeout=get_config()["timeouts"]["ollama_s"])
    return _clients[url]


def chat(node: str, model: str, messages: list[dict[str, Any]], **kwargs: Any) -> str:
    cfg = get_config()["llm"]
    options = {"temperature": cfg["temperature"], "num_ctx": cfg["num_ctx"], **kwargs.pop("options", {})}
    resp = ollama_client(node).chat(
        model=model,
        messages=messages,
        options=options,
        keep_alive=cfg["keep_alive"],
        think=False,
        **kwargs,
    )
    return (resp.message.content or "").strip()
