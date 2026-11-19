"""Protocol pipeline: index PDFs/text, answer only from them, refuse when the answer is absent.

ingest_pdf(path) / ingest_text(path): PyMuPDF text extraction, section headings detected from
font size and weight (text files: short standalone lines), ~500-word chunks that keep their
section title, nomic-embed-text embeddings, stored in Chroma (data/chroma).

ask(question): top-4 chunks. If the best cosine similarity is below thresholds.doc_similarity,
or the model replies NOT_IN_PROTOCOLS, the result is the refusal
{"answer": None, "refused": True, "message": "Not in your indexed protocols."}.
Correct refusal is scored; do not weaken it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
import threading
import time
from pathlib import Path
from typing import Any

from backend import nodes
from backend.config import get_config, path

log = logging.getLogger("benchlog.docs")

REFUSAL = "Not in your indexed protocols."
NOT_FOUND = "NOT_IN_PROTOCOLS"

SYSTEM_PROMPT = (
    "You answer questions for a lab notebook using ONLY the protocol excerpts provided. "
    "Do not use outside knowledge. Rules:\n"
    "1. If the excerpts state the answer to exactly this question, give the shortest complete answer, "
    "using the excerpt's own wording, and name the section it came from.\n"
    "2. Check every detail of the question (names, dates, numbers, places) against the excerpts. "
    "If the question asks about something the excerpts do not state, or a detail in the question "
    f"does not match the excerpts, the answer is not there: set answer to exactly {NOT_FOUND}.\n"
    "3. Never guess or combine facts to invent an answer.\n"
    'Reply as JSON: {"answer": "...", "section": "<section title>", "quote": "<short supporting quote>"}'
)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "section": {"type": "string"}, "quote": {"type": "string"}},
    "required": ["answer", "section"],
}

_chroma: dict[str, Any] = {}
_chroma_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def collection():
    with _chroma_lock:
        if "col" not in _chroma:
            import chromadb

            client = chromadb.PersistentClient(
                path=str(path("chroma")), settings=chromadb.Settings(anonymized_telemetry=False)
            )
            _chroma["client"] = client
            _chroma["col"] = client.get_or_create_collection(
                get_config()["docs"]["collection"], metadata={"hnsw:space": "cosine"}
            )
        return _chroma["col"]


def embed(texts: list[str], kind: str) -> list[list[float]]:
    """nomic-embed-text needs task prefixes: search_document for chunks, search_query for questions."""
    prefix = "search_document: " if kind == "document" else "search_query: "
    resp = nodes.ollama_client("m5").embed(
        model=get_config()["models"]["embed"],
        input=[prefix + t for t in texts],
        keep_alive=get_config()["llm"]["keep_alive"],
    )
    return [list(e) for e in resp.embeddings]


# ---------------------------------------------------------------------------
# Parsing and chunking
# ---------------------------------------------------------------------------
def pdf_sections(pdf_path: str | Path) -> list[dict[str, Any]]:
    """[{"title", "text", "page"}] from a PDF. A heading is a short line larger or bolder than body text."""
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    lines: list[tuple[str, float, bool, int]] = []  # text, size, bold, page
    for pno, page in enumerate(doc, 1):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                size = max(s["size"] for s in spans)
                bold = all(s["flags"] & 16 for s in spans)
                lines.append((text, size, bold, pno))
    doc.close()
    if not lines:
        return []
    body = statistics.median(s for _, s, _, _ in lines)
    sections: list[dict[str, Any]] = []
    cur = {"title": Path(pdf_path).stem, "text": [], "page": 1}
    for text, size, bold, pno in lines:
        is_heading = len(text.split()) <= 14 and not text.endswith((".", ",", ";")) and (size >= body * 1.15 or bold)
        if is_heading:
            if cur["text"]:
                sections.append(cur)
            elif sections or cur["title"] == Path(pdf_path).stem:
                pass  # consecutive headings: keep the latest
            cur = {"title": text, "text": [], "page": pno}
        else:
            cur["text"].append(text)
    if cur["text"]:
        sections.append(cur)
    return [{"title": s["title"], "text": _join_lines(s["text"]), "page": s["page"]} for s in sections]


def _join_lines(lines: list[str]) -> str:
    """PDF lines -> paragraphs: join wrapped lines, fix hyphenated breaks."""
    out = ""
    for ln in lines:
        if out.endswith("-") and ln[:1].islower():
            out = out[:-1] + ln
        else:
            out = f"{out} {ln}" if out else ln
    return out


def text_sections(txt_path: str | Path) -> list[dict[str, Any]]:
    """Sections from plain text: a short line with no final punctuation, on its own, is a heading."""
    raw = Path(txt_path).read_text(encoding="utf-8", errors="replace")
    paras = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    sections: list[dict[str, Any]] = []
    cur = {"title": Path(txt_path).stem, "text": []}
    for p in paras:
        if "\n" not in p and len(p.split()) <= 12 and not p.endswith((".", "?", "!", ",", ";", ":")):
            if cur["text"]:
                sections.append(cur)
            cur = {"title": p.lstrip("#").strip(), "text": []}
        else:
            cur["text"].append(" ".join(p.split()))
    if cur["text"]:
        sections.append(cur)
    return [{"title": s["title"], "text": "\n\n".join(s["text"]), "page": None} for s in sections]


def chunk_sections(sections: list[dict[str, Any]], chunk_words: int) -> list[dict[str, Any]]:
    """~chunk_words-word chunks that never cross a section boundary and keep the section title."""
    chunks = []
    for sec in sections:
        sentences = re.split(r"(?<=[.!?])\s+", sec["text"])
        buf: list[str] = []
        n = 0
        for s in sentences:
            w = len(s.split())
            if buf and n + w > chunk_words:
                chunks.append({"section": sec["title"], "page": sec["page"], "text": " ".join(buf)})
                buf, n = buf[-2:], sum(len(x.split()) for x in buf[-2:])  # 2-sentence overlap
            buf.append(s)
            n += w
        if buf:
            chunks.append({"section": sec["title"], "page": sec["page"], "text": " ".join(buf)})
    return chunks


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------
def ingest(file_path: str | Path, source: str | None = None) -> dict[str, Any]:
    """Index a .pdf, .txt or .md file. Re-ingesting the same source replaces its chunks."""
    t0 = time.time()
    file_path = Path(file_path)
    source = source or file_path.name
    if file_path.suffix.lower() == ".pdf":
        sections = pdf_sections(file_path)
    else:
        sections = text_sections(file_path)
    chunks = chunk_sections(sections, int(get_config()["docs"]["chunk_words"]))
    if not chunks:
        raise ValueError(f"no text found in {file_path.name}")
    doc_id = hashlib.sha256(file_path.read_bytes()).hexdigest()[:16]
    texts = [f"Section: {c['section']}\n{c['text']}" for c in chunks]
    vectors = embed(texts, "document")
    col = collection()
    col.delete(where={"source": source})
    col.upsert(
        ids=[f"{doc_id}:{i}" for i in range(len(chunks))],
        embeddings=vectors,
        documents=texts,
        metadatas=[
            {"source": source, "section": c["section"], "page": c["page"] or 0, "chunk": i, "doc_id": doc_id}
            for i, c in enumerate(chunks)
        ],
    )
    latency = round(time.time() - t0, 2)
    log.info("docs.ingest node=M5 source=%s sections=%d chunks=%d latency=%.2fs", source, len(sections), len(chunks), latency)
    return {
        "source": source,
        "doc_id": doc_id,
        "sections": [s["title"] for s in sections],
        "chunks": len(chunks),
        "words": sum(len(c["text"].split()) for c in chunks),
        "node": "M5",
        "latency_s": latency,
    }


ingest_pdf = ingest
ingest_text = ingest


def list_protocols() -> list[dict[str, Any]]:
    got = collection().get(include=["metadatas"])
    by: dict[str, dict[str, Any]] = {}
    for m in got["metadatas"] or []:
        d = by.setdefault(m["source"], {"source": m["source"], "chunks": 0, "sections": []})
        d["chunks"] += 1
        if m["section"] not in d["sections"]:
            d["sections"].append(m["section"])
    return sorted(by.values(), key=lambda d: d["source"])


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(text)}


def ungrounded_numbers(text: str, context: str) -> list[str]:
    """Numbers in `text` (2+ digits, commas ignored) that never appear in `context`."""
    have = _numbers(context)
    return sorted(n for n in _numbers(text) if len(n.replace(".", "")) >= 2 and n not in have)


def _refusal(question: str, reason: str, hits: list[dict[str, Any]], t0: float, **extra: Any) -> dict[str, Any]:
    return {
        "question": question,
        "answer": None,
        "refused": True,
        "message": REFUSAL,
        "reason": reason,
        "retrieved": hits,
        "best_similarity": hits[0]["similarity"] if hits else None,
        "node": "M5",
        "latency_s": round(time.time() - t0, 2),
        **extra,
    }


def ask(question: str, source: str | None = None) -> dict[str, Any]:
    """Answer from indexed protocols only (optionally only from `source`), or refuse."""
    t0 = time.time()
    cfg = get_config()
    col = collection()
    if col.count() == 0:
        return _refusal(question, "no protocols indexed", [], t0)
    where = {"source": source} if source else None
    res = col.query(
        query_embeddings=embed([question], "query"),
        n_results=int(cfg["docs"]["top_k"]),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    hits = [
        {
            "source": m["source"],
            "section": m["section"],
            "page": m["page"] or None,
            "similarity": round(1 - d, 3),
            "text": doc,
        }
        for doc, m, d in zip(res["documents"][0], res["metadatas"][0], res["distances"][0])
    ]
    if not hits or hits[0]["similarity"] < cfg["thresholds"]["doc_similarity"]:
        return _refusal(question, "best similarity below threshold", hits, t0)

    excerpts = "\n\n".join(
        f"[Excerpt {i} | Source: {h['source']} | Section: {h['section']}]\n{h['text'].split(chr(10), 1)[-1]}"
        for i, h in enumerate(hits, 1)
    )
    raw = nodes.chat(
        "m5",
        cfg["models"]["text"],
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Protocol excerpts:\n\n{excerpts}\n\nQuestion: {question}"},
        ],
        format=ANSWER_SCHEMA,
    )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"answer": raw, "section": ""}
    answer = str(parsed.get("answer", "")).strip()
    if not answer or NOT_FOUND in answer.upper().replace(" ", "_"):
        return _refusal(question, "model found no answer in the excerpts", hits, t0, raw=raw)
    # Grounding check: numbers are where adversarial questions and invented answers show up
    # ("4380 species" vs the text's 438,000; a year the text never gives).
    context = " ".join(h["text"] for h in hits)
    missing_q = ungrounded_numbers(question, context)
    if missing_q:
        return _refusal(question, f"question mentions {missing_q} which the excerpts do not", hits, t0, raw=raw)
    missing_a = ungrounded_numbers(answer, context)
    if missing_a:
        return _refusal(question, f"answer contains {missing_a} which the excerpts do not", hits, t0, raw=raw)

    section = str(parsed.get("section", "")).strip()
    cited = next((h for h in hits if h["section"].lower() == section.lower()), hits[0])
    latency = round(time.time() - t0, 2)
    log.info("docs.ask node=M5 best_sim=%.3f latency=%.2fs", hits[0]["similarity"], latency)
    return {
        "question": question,
        "answer": answer,
        "refused": False,
        "citation": {"source": cited["source"], "section": cited["section"], "page": cited["page"]},
        "quote": parsed.get("quote"),
        "retrieved": hits,
        "best_similarity": hits[0]["similarity"],
        "model": cfg["models"]["text"],
        "node": "M5",
        "latency_s": latency,
    }
