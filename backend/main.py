"""BenchLog FastAPI orchestrator (runs on the M5).

Endpoints (also served under /api for the frontend's dev proxy and built bundle):
  POST /entry        multipart: file?, text?, question?, experiment_id -> API-contract entry
  GET  /entries      ?experiment_id=&date=YYYY-MM-DD
  GET  /entries/{id}
  GET  /verify       recompute the hash chain; reports the first broken entry
  GET  /status       node health + which node serves each job + models
  GET  /export       ?date=&experiment_id= -> Markdown lab log with hashes
  POST /protocols    upload a PDF/TXT to index;  GET /protocols  list indexed protocols
  GET  /experiments, POST /experiments
  GET  /health
Media is served from /media. A built frontend (frontend/dist) is served at /.
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend import nodes
from backend.config import REPO_ROOT, get_config
from backend.router import EntryBuilder, save_upload
from backend.store import DEFAULT_EXPERIMENT, get_store

log = logging.getLogger("benchlog.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

_stop = threading.Event()


def _health_loop() -> None:
    interval = get_config()["health"]["interval_s"]
    while not _stop.is_set():
        try:
            nodes.refresh()
        except Exception as exc:  # noqa: BLE001
            log.warning("health refresh failed: %s", exc)
        _stop.wait(interval)


def _warmup() -> None:
    """Load the VLM (at the shared context size) and embedder so the first capture is fast."""
    try:
        m = get_config()["models"]
        nodes.chat("m5", m["vision"], [{"role": "user", "content": "ok"}], options={"num_predict": 1})
        nodes.ollama_client("m5").embed(model=m["embed"], input=["warmup"])
        log.info("warmup done")
    except Exception as exc:  # noqa: BLE001
        log.warning("warmup failed: %s", exc)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _stop.clear()
    threading.Thread(target=_health_loop, daemon=True, name="health").start()
    if get_config().get("llm", {}).get("warmup", True):
        threading.Thread(target=_warmup, daemon=True, name="warmup").start()
    yield
    _stop.set()


app = FastAPI(title="BenchLog", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
api = APIRouter()


@api.get("/health")
def health() -> dict:
    return {"ok": True, "models": get_config()["models"]}


@api.post("/entry")
def create_entry(
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    question: str | None = Form(default=None),
    experiment_id: str = Form(default=DEFAULT_EXPERIMENT),
) -> dict:
    store = get_store()
    tmp: Path | None = None
    try:
        if file is not None and file.filename:
            tmp = save_upload(file.file, Path(file.filename).suffix)
            if tmp.stat().st_size == 0:
                raise HTTPException(400, "uploaded file is empty")
        out = EntryBuilder(store).build(
            file_path=tmp,
            filename=file.filename if file else None,
            content_type=file.content_type if file else None,
            text=text,
            question=question,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
    return store.add_entry(
        type=out["type"],
        summary=out["summary"],
        details=out["details"],
        artifacts=out["artifacts"],
        node=out["node"],
        experiment_id=experiment_id or DEFAULT_EXPERIMENT,
    )


@api.get("/entries")
def list_entries(experiment_id: str | None = None, date: str | None = None) -> list[dict]:
    from backend.store import to_contract

    return [to_contract(e) for e in get_store().list_entries(experiment_id, date)]


@api.get("/entries/{entry_id}")
def get_entry(entry_id: str) -> dict:
    from backend.store import to_contract

    e = get_store().get_entry(entry_id)
    if e is None:
        raise HTTPException(404, "no such entry")
    return to_contract(e)


@api.get("/verify")
def verify() -> dict:
    return get_store().verify_report()


@api.get("/status")
def status() -> dict:
    s = nodes.status()
    s["models"] = get_config()["models"]
    s["offline"] = True
    s["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return s


@api.get("/experiments")
def experiments() -> list[dict]:
    return get_store().list_experiments()


@api.post("/experiments")
def create_experiment(name: str = Form(...)) -> dict:
    return get_store().create_experiment(name)


@api.get("/protocols")
def protocols() -> list[dict]:
    from backend.pipelines import docs

    return docs.list_protocols()


@api.post("/protocols")
def upload_protocol(file: UploadFile = File(...)) -> dict:
    from backend.pipelines import docs

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".txt", ".md"):
        raise HTTPException(400, "protocols must be .pdf, .txt or .md")
    tmp = save_upload(file.file, suffix)
    try:
        get_store().save_media(tmp, file.filename)
        return docs.ingest(tmp, source=file.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp.unlink(missing_ok=True)


@api.get("/export", response_class=PlainTextResponse)
def export(date: str | None = None, experiment_id: str | None = None) -> PlainTextResponse:
    store = get_store()
    entries = store.list_entries(experiment_id, date)
    exps = {e["id"]: e["name"] for e in store.list_experiments()}
    rep = store.verify_report()
    lines = [
        f"# BenchLog lab log{f' — {date}' if date else ''}",
        "",
        f"- Experiment: {exps.get(experiment_id, experiment_id) if experiment_id else 'all'}",
        f"- Exported: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Entries: {len(entries)}",
        f"- Hash chain: {'verified, ' + str(rep['verified']) + ' entries' if rep['ok'] else 'BROKEN at ' + str(rep['first_broken'])}",
        "- All inference ran locally on open-weight models; nothing left the lab network.",
        "",
    ]
    for e in entries:
        d = e["details"]
        lines += [f"## {e['created_at'][11:16]} · {e['type']} · {exps.get(e['experiment_id'], e['experiment_id'])}", ""]
        lines.append(e["summary"])
        lines.append("")
        if d.get("question"):
            lines.append(f"**Question:** {d['question']}  ")
        if e["type"] == "photo" and "opencv" in d:
            lines.append(f"**Counts:** OpenCV {d['opencv']['count']} · VLM estimate {d.get('vlm_count_estimate')}  ")
        if e["type"] in ("photo", "video") and d.get("answer"):
            lines.append(f"**Model answer:** {' '.join(d['answer'].split())}  ")
        if e["type"] == "voice" and d.get("transcript"):
            lines.append(f"**Transcript:** {d['transcript']}  ")
        if e["type"] == "protocol_qa" and not d.get("refused") and d.get("citation"):
            c = d["citation"]
            lines.append(f"**Source:** {c['source']} § {c['section']}  ")
        if e["type"] == "analysis":
            lines += ["", "```python", d.get("code", "").rstrip(), "```", ""]
            if d.get("stdout"):
                lines += ["Output:", "```", d["stdout"].rstrip()[:2000], "```", ""]
            lines.append(f"Executed: exit code {d.get('exit_code')} on {d.get('sandbox_node')}  ")
        for a in e["artifacts"]:
            lines.append(f"- {a['kind']}: `{a['path']}`")
        lines += ["", f"<sub>node {e['node']} · hash `{e['hash']}` · prev `{e['prev_hash']}`</sub>", ""]
    fname = f"benchlog-{date or datetime.now().strftime('%Y-%m-%d')}.md"
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@api.get("/media/{rel:path}")
def media(rel: str) -> FileResponse:
    root = get_store().media_dir.resolve()
    target = (root / rel).resolve()
    if not target.is_file() or root not in target.parents:
        raise HTTPException(404, "not found")
    return FileResponse(target)


app.include_router(api)
app.include_router(api, prefix="/api")

_dist = REPO_ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
