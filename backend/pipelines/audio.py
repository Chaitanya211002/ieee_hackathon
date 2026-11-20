"""Audio pipeline: speech to text plus sound identification, WIN first with an M5 fallback.

transcribe(path) and classify_sound(path) call the WIN service (docs/win-service-contract.md);
on any failure they run locally: mlx-whisper (Mac GPU) and the AST AudioSet classifier through
transformers. analyze(path, question) combines both into one notebook entry and, when a
question is asked, answers it from the transcript and sound labels with the text model.
Only sound labels with score >= thresholds.sound_conf appear in the summary.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from backend import nodes
from backend.config import get_config

log = logging.getLogger("benchlog.audio")

SR = 16_000
SPEECH_LABELS = re.compile(r"speech|speaking|conversation|narration|monologue|babbling", re.I)
TRANSCRIBE_Q = re.compile(r"^\s*(please\s+)?(transcribe|write down|what (is|was) said)", re.I)

_ast: dict[str, Any] = {}
_ast_lock = threading.Lock()
_whisper_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Remote (WIN service)
# ---------------------------------------------------------------------------
def _post_file(node: str, endpoint: str, path: Path) -> dict[str, Any]:
    url = nodes.node_url(node, "service")
    with open(path, "rb") as fh:
        r = httpx.post(
            f"{url}{endpoint}",
            files={"file": (path.name, fh)},
            timeout=get_config()["timeouts"]["win_service_s"],
        )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Local (M5)
# ---------------------------------------------------------------------------
def load_audio(path: str | Path) -> np.ndarray:
    """Decode any audio/video file to 16 kHz mono float32 with ffmpeg."""
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", str(SR), "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


def _local_transcribe(path: Path) -> dict[str, Any]:
    import mlx_whisper

    cfg = get_config()
    with _whisper_lock:  # MLX is not safe to call from several threads at once
        res = mlx_whisper.transcribe(
            str(path),
            path_or_hf_repo=cfg["models"]["whisper"],
            condition_on_previous_text=False,
            verbose=None,
        )
    limit = cfg["thresholds"]["no_speech_prob"]
    heard = [s for s in res.get("segments", []) if s["text"].strip()]
    segs = [
        {"start": round(float(s["start"]), 2), "end": round(float(s["end"]), 2), "text": s["text"].strip()}
        for s in heard
        if s.get("no_speech_prob", 0) < limit
    ]
    out = {"text": " ".join(s["text"] for s in segs).strip(), "segments": segs, "language": res.get("language", "")}
    doubted = " ".join(s["text"].strip() for s in heard if s.get("no_speech_prob", 0) >= limit)
    if doubted:  # Whisper produced words here but rated the audio as probably not speech
        out["dropped_text"] = doubted
    return out


def _load_ast() -> dict[str, Any]:
    with _ast_lock:
        if not _ast:
            from transformers import ASTFeatureExtractor, ASTForAudioClassification

            name = get_config()["models"]["sound"]
            _ast["extractor"] = ASTFeatureExtractor.from_pretrained(name)
            _ast["model"] = ASTForAudioClassification.from_pretrained(name).eval()
            _ast["labels"] = [_ast["model"].config.id2label[i] for i in range(_ast["model"].config.num_labels)]
    return _ast


def _local_classify(path: Path, top_k: int = 3) -> dict[str, Any]:
    """AST over 10 s windows; a label's clip score is its best window. Sigmoid, as AudioSet is multi-label."""
    import torch

    ast = _load_ast()
    audio = load_audio(path)
    acfg = get_config()["audio"]
    win, hop = int(acfg["window_s"] * SR), int(acfg["hop_s"] * SR)
    starts = [0] if audio.size <= win else list(range(0, audio.size - win + hop, hop))
    chunks = [audio[s : s + win] for s in starts] or [np.zeros(SR, np.float32)]
    with _ast_lock, torch.inference_mode():
        inputs = ast["extractor"](chunks, sampling_rate=SR, return_tensors="pt")
        probs = torch.sigmoid(ast["model"](**inputs).logits).numpy()
    best = probs.max(axis=0)
    order = np.argsort(best)[::-1][:top_k]
    return {"labels": [{"label": ast["labels"][i], "score": round(float(best[i]), 3)} for i in order]}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------
def transcribe(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    res, node, meta = nodes.run_job(
        "audio",
        remote=lambda n: _post_file(n, "/transcribe", path),
        local=lambda: _local_transcribe(path),
    )
    return {**res, "node": node, "latency_s": meta["latency_s"], **_fallback(meta)}


def classify_sound(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    res, node, meta = nodes.run_job(
        "audio",
        remote=lambda n: _post_file(n, "/classify_sound", path),
        local=lambda: _local_classify(path),
    )
    return {**res, "node": node, "latency_s": meta["latency_s"], **_fallback(meta)}


def _fallback(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in meta.items() if k.startswith("fallback")}


def has_speech(labels: list[dict[str, Any]]) -> bool:
    floor = get_config()["thresholds"]["speech_label"]
    return any(SPEECH_LABELS.search(lab["label"]) and lab["score"] >= floor for lab in labels)


def answer_question(question: str, transcript: str, labels: list[dict[str, Any]]) -> dict[str, Any]:
    """Answer a question about a recording using only its transcript and sound labels (M5 text model)."""
    model = get_config()["models"]["text"]
    label_txt = ", ".join(f"{lab['label']} ({lab['score']:.2f})" for lab in labels) or "none"
    prompt = (
        f'Transcript of the recording:\n"""\n{transcript or "(no speech detected)"}\n"""\n'
        f"Sound classifier labels with confidence (AudioSet classes): {label_txt}\n\n"
        f"Question: {question}\n\n"
        "Answer in one short sentence using only the transcript and the sound labels. If the question "
        "asks what sound it is, name the sound in plain words based on the labels. If the answer is not "
        "in the recording, say so."
    )
    t0 = time.time()
    answer = nodes.chat("m5", model, [{"role": "user", "content": prompt}])
    return {"answer": answer, "model": model, "node": "M5", "latency_s": round(time.time() - t0, 2)}


def analyze(path: str | Path, question: str | None = None) -> dict[str, Any]:
    """Full voice entry: transcript + top-3 sound labels (+ answer to an optional question)."""
    t0 = time.time()
    sound_conf = get_config()["thresholds"]["sound_conf"]
    tr = transcribe(path)
    cl = classify_sound(path)
    labels = cl.get("labels", [])[:3]
    text = tr.get("text", "")
    speech = has_speech(labels)
    doubted = tr.get("dropped_text", "")
    if text and not speech and len(text.split()) <= get_config()["thresholds"]["hallucination_max_words"]:
        # Short text on a clip the classifier hears no speech in is a Whisper hallucination.
        text, doubted = "", f"{text} {doubted}".strip()

    alerts = [lab for lab in labels if lab["score"] >= sound_conf and not SPEECH_LABELS.search(lab["label"])]
    result: dict[str, Any] = {
        "transcript": text,
        "segments": tr.get("segments", []),
        "language": tr.get("language"),
        "sound_labels": labels,
        "sound_alerts": alerts,
        "lab_events": cl.get("lab_events", []),
        "speech_detected": bool(text),
        # Words Whisper produced but the filters above did not trust. Shown as low confidence, never
        # used for the summary or for answers.
        **({"unconfirmed_transcript": doubted} if doubted else {}),
        "transcribe_node": tr["node"],
        "classify_node": cl["node"],
        "node": tr["node"],
        "transcribe_latency_s": tr["latency_s"],
        "classify_latency_s": cl["latency_s"],
        **{f"transcribe_{k}": v for k, v in tr.items() if k.startswith("fallback")},
    }
    if question and question.strip():
        if TRANSCRIBE_Q.search(question):
            result["answer"] = text or "No speech detected."
        else:
            qa = answer_question(question, text, labels)
            result["answer"] = qa["answer"]
            result["answer_latency_s"] = qa["latency_s"]
        result["question"] = question

    parts = []
    if text:
        parts.append(f'"{text[:160]}{"…" if len(text) > 160 else ""}"')
    else:
        parts.append("No speech")
    if alerts:
        parts.append("Sounds: " + ", ".join(f"{a['label']} ({a['score']:.2f})" for a in alerts))
    result["summary"] = " · ".join(parts)
    result["latency_s"] = round(time.time() - t0, 2)
    return result
