"""File-type routing: decide which pipeline handles a capture and shape its notebook entry.

Routing is by MIME type / extension and simple text rules, never by an LLM:
  image/*            -> vision  -> "photo"
  audio/*            -> audio   -> "voice"
  video/*            -> video   -> "video"   (a video container with no video stream -> audio)
  .pdf / .txt / .md  -> docs ingest, then ask if a question came with it -> "protocol_qa" (or "note")
  .csv / .tsv / .xlsx-free tabular + request -> code -> "analysis"
  text "code: ..." or a code-like request -> code -> "analysis"
  other text: a question -> docs ask -> "protocol_qa"; otherwise a log note -> "note"
Node fallback lives in backend/nodes.py; pipelines call it themselves.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.store import Store

log = logging.getLogger("benchlog.router")

DOC_EXT = {".pdf", ".txt", ".md"}
DATA_EXT = {".csv", ".tsv"}
QUESTION_START = re.compile(
    r"^\s*(what|which|who|whom|whose|when|where|why|how|is|are|was|were|does|do|did|can|could|should|"
    r"would|will|according|in what|list|explain|describe|summari[sz]e)\b",
    re.I,
)
CODE_STRONG = re.compile(
    r"```|^\s*(def |class |import |from \w+ import )|complete (this|the) (python )?function|"
    r"\bpython\b|\b(write|generate|create) (a |some )?(function|script|code|program)\b",
    re.I | re.M,
)
CODE_WEAK = re.compile(r"\b(plot|graph|chart|histogram|regression|standard curve|fit a|calculate|compute)\b", re.I)
NOTE_PREFIX = re.compile(r"^\s*(note|log)\s*:\s*", re.I)
ASK_PREFIX = re.compile(r"^\s*(q|ask|question)\s*:\s*", re.I)
CODE_PREFIX = re.compile(r"^\s*code\s*:\s*", re.I)


def kind_of_file(filename: str, content_type: str | None) -> str:
    """image | audio | video | doc | data | other."""
    ext = Path(filename).suffix.lower()
    mime = (content_type or "").split(";")[0].strip().lower()
    if not mime or mime == "application/octet-stream":
        mime = mimetypes.guess_type(filename)[0] or ""
    if ext in DOC_EXT or mime in ("application/pdf", "text/plain", "text/markdown"):
        return "doc"
    if ext in DATA_EXT or mime in ("text/csv", "text/tab-separated-values"):
        return "data"
    for k in ("image", "audio", "video"):
        if mime.startswith(k + "/"):
            return k
    return "other"


def kind_of_text(text: str) -> str:
    """code | question | note."""
    if CODE_PREFIX.match(text) or CODE_STRONG.search(text):
        return "code"
    if NOTE_PREFIX.match(text):
        return "note"
    if ASK_PREFIX.match(text) or text.strip().endswith("?") or QUESTION_START.match(text):
        return "question"
    if CODE_WEAK.search(text):  # an imperative like "plot OD vs time", not a question
        return "code"
    return "note"


def _strip_prefix(text: str) -> str:
    for p in (CODE_PREFIX, NOTE_PREFIX, ASK_PREFIX):
        text = p.sub("", text, count=1)
    return text.strip()


def _one_line(text: str, limit: int = 200) -> str:
    line = " ".join((text or "").split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


class EntryBuilder:
    """Turns a capture into (type, summary, details, artifacts, node) and saves its media."""

    def __init__(self, store: Store):
        self.store = store

    def _save(self, src: str | Path | bytes, name: str) -> str:
        return "/media/" + self.store.save_media(src, name)

    # ---------------------------------------------------------------------
    def build(
        self, *, file_path: Path | None, filename: str | None, content_type: str | None,
        text: str | None, question: str | None, follow_up_of: str | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        t0 = time.time()
        text = (text or "").strip()
        question = (question or "").strip() or None
        if follow_up_of and file_path is None:
            q = question or text
            if not q:
                raise ValueError("a follow-up needs a question")
            out = self._follow_up(follow_up_of, _strip_prefix(q))
        elif file_path is not None:
            kind = kind_of_file(filename or file_path.name, content_type)
            if kind == "video" and not _has_video_stream(file_path):
                kind = "audio"  # e.g. an audio-only .webm from MediaRecorder
            q = question or (text or None)
            handler = {
                "image": self._photo, "audio": self._voice, "video": self._video,
                "doc": self._doc, "data": self._data,
            }.get(kind)  # fmt: skip
            if handler is None:
                raise ValueError(f"unsupported file type: {filename} ({content_type})")
            out = handler(file_path, filename or file_path.name, q)
        elif text:
            k = kind_of_text(text)
            out = {"code": self._code_text, "question": self._question, "note": self._note}[k](text)
        else:
            raise ValueError("send a file, text, or both")
        out["details"]["routing"] = {"route": out.pop("route"), "total_latency_s": round(time.time() - t0, 2)}
        return out

    # ---------------------------------------------------------------------
    def _photo(self, path: Path, name: str, q: str | None) -> dict[str, Any]:
        from backend.pipelines import vision

        media = self._save(path, name)
        with tempfile.TemporaryDirectory() as tmp:
            r = vision.analyze(path, q, out_dir=tmp)
            artifacts = self._vision_artifacts(r, media)
        return {"route": "vision", "type": "photo", "summary": r["summary"],
                "details": {**r, "media": {"kind": "image", "path": media}},
                "artifacts": artifacts, "node": "M5"}  # fmt: skip

    def _vision_artifacts(self, r: dict[str, Any], media: str) -> list[dict[str, str]]:
        """Keep the images a vision result made (annotated plate, zoom crop) and point the result at them.

        Call while the pipeline's temp folder still exists. The photo itself stays the first artifact.
        """
        artifacts = [{"kind": "image", "path": media}]
        for key, field, name in (
            ("opencv", "annotated_path", "colonies_annotated.jpg"),
            ("zoom", "crop_path", "zoom_crop.jpg"),
        ):
            if key in r:
                r[key][field] = self._save(r[key][field], name)
                artifacts.append({"kind": "image", "path": r[key][field]})
        return artifacts

    def _local(self, media_path: str) -> Path:
        """/media/<rel> URL -> file in the store's media folder."""
        rel = media_path.removeprefix("/media/")
        p = (self.store.media_dir / rel).resolve()
        if self.store.media_dir.resolve() not in p.parents or not p.is_file():
            raise ValueError("the original media for that entry is missing")
        return p

    def _follow_up(self, parent_id: str, q: str) -> dict[str, Any]:
        """Ask another question about an earlier photo or video, with the earlier Q&A as context."""
        from backend.pipelines import video, vision

        parent = self.store.get_entry(parent_id)
        if parent is None:
            raise ValueError(f"no entry {parent_id}")
        if parent["type"] not in ("photo", "video"):
            raise ValueError("follow-up questions work on photo and video entries")
        chain = [parent]  # parent, its parent, ... up to the original capture
        while chain[-1]["details"].get("follow_up_of") and len(chain) < 10:
            up = self.store.get_entry(chain[-1]["details"]["follow_up_of"])
            if up is None:
                break
            chain.append(up)
        root = chain[-1]
        history = [
            {"question": e["details"].get("question") or (vision.DESCRIBE_PROMPT if e["type"] == "photo"
                                                         else video.DESCRIBE_PROMPT),
             "answer": e["details"].get("answer", "")}
            for e in reversed(chain)
        ]  # fmt: skip
        thread = {"follow_up_of": parent_id, "thread_root": root["id"], "history": history}
        media = root["details"].get("media")
        media_path = media["path"] if isinstance(media, dict) else (media or root["artifacts"][0]["path"])

        if root["type"] == "photo":
            with tempfile.TemporaryDirectory() as tmp:
                r = vision.analyze(self._local(media_path), q, out_dir=tmp, history=history)
                artifacts = self._vision_artifacts(r, media_path)
            return {"route": "vision.follow_up", "type": "photo", "summary": r["summary"],
                    "details": {**r, **thread, "media": {"kind": "image", "path": media_path}},
                    "artifacts": artifacts, "node": "M5"}  # fmt: skip

        frames = root["details"].get("frames", [])
        local = [{**f, "path": str(self._local(f["path"]))} for f in frames]
        v = video.ask_frames(local, q, history)
        summary = " ".join(v["answer"].split())
        return {"route": "video.follow_up", "type": "video",
                "summary": summary if len(summary) <= 200 else summary[:199] + "…",
                "details": {"question": q, "answer": v["answer"], "frames": frames, "duration_s": root["details"].get("duration_s"),
                            "model": v["model"], "vlm_latency_s": v["latency_s"], "node": "M5", "audio": None,
                            **thread, "media": {"kind": "video", "path": media_path}},
                "artifacts": [{"kind": "image", "path": f["path"]} for f in frames], "node": "M5"}  # fmt: skip

    def _voice(self, path: Path, name: str, q: str | None) -> dict[str, Any]:
        from backend.pipelines import audio

        media = self._save(path, name)
        r = audio.analyze(path, q)
        artifacts = []
        if r["transcript"]:
            artifacts.append({"kind": "transcript", "path": self._save(r["transcript"].encode(), "transcript.txt")})
        summary = r["summary"]
        if q and r.get("answer"):
            summary = f"{_one_line(r['answer'], 160)} · {summary}"
        return {"route": "audio", "type": "voice", "summary": summary,
                "details": {**r, "media": {"kind": "audio", "path": media}},
                "artifacts": artifacts, "node": r["node"]}  # fmt: skip

    def _video(self, path: Path, name: str, q: str | None) -> dict[str, Any]:
        from backend.pipelines import video

        media = self._save(path, name)
        with tempfile.TemporaryDirectory() as tmp:
            r = video.analyze(path, q, out_dir=tmp)
            for f in r["frames"]:
                f["path"] = self._save(f["path"], f"frame_{f['index']:02d}.jpg")
        artifacts = [{"kind": "image", "path": f["path"]} for f in r["frames"]]
        node = "M5"
        if r.get("audio") and r["audio"].get("transcript"):
            artifacts.append(
                {"kind": "transcript", "path": self._save(r["audio"]["transcript"].encode(), "transcript.txt")}
            )
        return {"route": "video", "type": "video", "summary": r["summary"],
                "details": {**r, "media": {"kind": "video", "path": media}},
                "artifacts": artifacts, "node": node}  # fmt: skip

    def _doc(self, path: Path, name: str, q: str | None) -> dict[str, Any]:
        from backend.pipelines import docs

        media = self._save(path, name)
        info = docs.ingest(path, source=name)
        if not q:
            return {"route": "docs.ingest", "type": "note",
                    "summary": f"Indexed protocol {name}: {info['chunks']} chunks, sections: {', '.join(info['sections'][:5])}",
                    "details": {"kind": "protocol_indexed", **info, "media": {"kind": "document", "path": media}},
                    "artifacts": [], "node": "M5"}  # fmt: skip
        r = docs.ask(q, source=name)
        return self._qa_entry(r, {"indexed": info, "media": {"kind": "document", "path": media}})

    def _data(self, path: Path, name: str, q: str | None) -> dict[str, Any]:
        media = self._save(path, name)
        prompt = (
            _strip_prefix(q)
            if q
            else f"Summarise {name}: print basic statistics for each column and plot the numeric columns."
        )
        out = self._run_code(prompt, {name: path.read_bytes()})
        out["details"]["media"] = {"kind": "data", "path": media}
        return out

    def _code_text(self, text: str) -> dict[str, Any]:
        prompt = _strip_prefix(text)
        if not prompt:
            raise ValueError("write what the code should do after 'code:'")
        return self._run_code(prompt, {})

    def _run_code(self, prompt: str, files: dict[str, bytes]) -> dict[str, Any]:
        from backend.pipelines import code

        with tempfile.TemporaryDirectory() as tmp:
            r = code.generate(prompt, files=files, out_dir=tmp)
            r["plots"] = [self._save(p, Path(p).name) for p in r["plots"]]
        artifacts = [{"kind": "code", "path": self._save(r["code"].encode(), "analysis.py")}]
        artifacts += [{"kind": "plot", "path": p} for p in r["plots"]]
        first_out = next((ln for ln in r["stdout"].splitlines() if ln.strip()), "")
        if r["ok"]:
            summary = f"Executed OK ({len(r['attempts'])} attempt{'s' * (len(r['attempts']) > 1)})"
            summary += f" · {_one_line(first_out, 120)}" if first_out else ""
            summary += f" · {len(r['plots'])} plot(s)" if r["plots"] else ""
        else:
            last = next((ln for ln in reversed(r["stderr"].splitlines()) if ln.strip()), "error")
            summary = f"Code failed after {len(r['attempts'])} attempts: {_one_line(last, 120)}"
        return {"route": "code", "type": "analysis", "summary": summary, "details": r,
                "artifacts": artifacts, "node": r["coder_node"]}  # fmt: skip

    def _question(self, text: str) -> dict[str, Any]:
        from backend.pipelines import docs

        return self._qa_entry(docs.ask(_strip_prefix(text)), {})

    def _qa_entry(self, r: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        if r["refused"]:
            summary = r["message"]
        else:
            c = r["citation"]
            summary = f"{_one_line(r['answer'], 160)} [{c['source']} § {c['section']}]"
        for h in r.get("retrieved", []):
            h["text"] = h["text"][:600]
        return {"route": "docs.ask", "type": "protocol_qa", "summary": summary, "details": {**r, **extra},
                "artifacts": [], "node": "M5"}  # fmt: skip

    def _note(self, text: str) -> dict[str, Any]:
        body = _strip_prefix(text)
        return {"route": "note", "type": "note", "summary": _one_line(body), "details": {"text": body},
                "artifacts": [], "node": "M5"}  # fmt: skip


def _has_video_stream(path: Path) -> bool:
    from backend.pipelines.video import probe

    try:
        info = probe(path)
        return bool(info.get("width")) and info["duration"] > 0
    except Exception:  # noqa: BLE001
        return False


def save_upload(upload_file, suffix: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    with tmp:
        shutil.copyfileobj(upload_file, tmp)
    return Path(tmp.name)
