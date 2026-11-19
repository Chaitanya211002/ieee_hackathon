"""Append-only event log for debugging: data/logs/events.jsonl, one JSON object per line.

What goes in: every capture (ok, rejected or crashed, with timings, nodes and fallbacks),
node up/down changes from the health loop, server start, and errors the browser reports.
Never raises: logging must not break a request. Read it with scripts/diagnose.py.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any

from backend.config import path

log = logging.getLogger("benchlog.events")
_lock = threading.Lock()


def record(event: str, **fields: Any) -> None:
    try:
        row = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), "event": event, **fields}
        line = json.dumps(row, default=str, ensure_ascii=False)
        logs = path("logs")
        logs.mkdir(parents=True, exist_ok=True)
        with _lock, open(logs / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        log.warning("could not write event %s: %s", event, exc)


def fallbacks(details: dict[str, Any]) -> list[dict[str, Any]]:
    """Every fallback recorded anywhere in an entry's details (WIN failed -> M5 took over)."""
    found: list[dict[str, Any]] = []

    def walk(obj: Any, where: str) -> None:
        if isinstance(obj, dict):
            frm = obj.get("fallback_from") or obj.get("transcribe_fallback_from")
            if frm:
                err = obj.get("fallback_error") or obj.get("transcribe_fallback_error")
                found.append({"where": where or "entry", "from": frm, "error": str(err)[:300]})
            for k, v in obj.items():
                if k not in ("fallback_from", "transcribe_fallback_from"):
                    walk(v, f"{where}.{k}" if where else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{where}[{i}]")

    walk(details, "")
    return found
