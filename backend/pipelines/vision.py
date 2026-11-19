"""Image pipeline: Qwen3-VL description / Q&A, plus an OpenCV colony count for plates.

Pure functions: an image path (and optional question) in, a dict out. The VLM always runs on
the M5. VLMs are unreliable counters, so for colony questions the OpenCV blob count is
returned alongside the VLM estimate and the VLM number is labelled an estimate.
"""

from __future__ import annotations

import base64
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from backend import nodes
from backend.config import get_config

log = logging.getLogger("benchlog.vision")

SYSTEM_PROMPT = (
    "You are the vision assistant in BenchLog, an electronic lab notebook used at a wet-lab bench. "
    "Photos are often culture plates, agarose gels, microscopy fields, tube and bottle labels, "
    "instrument displays or handwritten notes, but they can show anything. "
    "Answer the user's question directly in the first sentence, then add only the detail that helps. "
    "When asked to count, count every instance carefully, including partly hidden or small ones, "
    "and give the number as digits. When asked to read text, copy it exactly as written. "
    "If something is not visible or cannot be determined, say so instead of guessing."
)
DESCRIBE_PROMPT = (
    "Describe this image for a lab notebook entry in 2-3 sentences: what it shows, any visible "
    "text or labels, and anything notable (contamination, bands, colonies, readings)."
)

COUNT_RE = re.compile(r"\b(how many|count|number of)\b", re.I)
COLONY_RE = re.compile(r"\b(colon(y|ies)|cfu|plate|petri|agar|blobs?)\b", re.I)


def _encode(image_path: str | Path, max_side: int) -> str:
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"could not read image {image_path}")
    h, w = img.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("could not encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def describe(image_path: str | Path, question: str | None = None) -> dict[str, Any]:
    """Ask Qwen3-VL about one image. Returns {"answer", "question", "node", "latency_s", "model"}."""
    cfg = get_config()
    model = cfg["models"]["vision"]
    img = _encode(image_path, cfg["vision"]["max_side"])
    prompt = question.strip() if question and question.strip() else DESCRIBE_PROMPT
    t0 = time.time()
    answer = nodes.chat(
        "m5",
        model,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt, "images": [img]},
        ],
    )
    latency = round(time.time() - t0, 2)
    log.info("vision.describe node=M5 latency=%.2fs", latency)
    return {"answer": answer, "question": question, "model": model, "node": "M5", "latency_s": latency}


def count_colonies(image_path: str | Path, out_path: str | Path | None = None) -> dict[str, Any]:
    """Count round blobs (colonies) with OpenCV and save an annotated image.

    grayscale -> blur -> adaptive threshold -> contours filtered by area and circularity.
    Works on either dark-on-light or light-on-dark plates (picks the polarity with more
    plausible blobs). Returns {"count", "annotated_path", "params", "latency_s"}.
    """
    c = get_config()["colonies"]
    t0 = time.time()
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"could not read image {image_path}")
    h, w = img.shape[:2]
    scale = min(1.0, c["max_side"] / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    max_area = c["max_area_frac"] * img.shape[0] * img.shape[1]

    best: list[np.ndarray] = []
    for mode in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):  # dark colonies, then light colonies
        th = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, mode, c["block_size"], c["c"])
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        keep = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < c["min_area"] or area > max_area:
                continue
            perim = cv2.arcLength(cnt, True)
            if perim == 0:
                continue
            circularity = 4 * np.pi * area / (perim * perim)
            if circularity < c["min_circularity"]:
                continue
            # A real colony is a filled blob in the mask. In the wrong polarity a colony shows
            # up as a thin ring whose edges are also round; its interior is mostly background.
            x, y, bw, bh = cv2.boundingRect(cnt)
            fill = np.zeros((bh, bw), np.uint8)
            cv2.drawContours(fill, [cnt - [x, y]], -1, 255, -1)
            inside = th[y : y + bh, x : x + bw][fill > 0]
            if inside.size and (inside > 0).mean() >= 0.8:
                keep.append(cnt)
        if len(keep) > len(best):
            best = keep

    annotated = img.copy()
    for cnt in best:
        (x, y), r = cv2.minEnclosingCircle(cnt)
        cv2.circle(annotated, (int(x), int(y)), int(r) + 2, (0, 255, 0), 2)
    cv2.putText(annotated, f"OpenCV count: {len(best)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    if out_path is None:
        out_path = Path(tempfile.mkdtemp(prefix="benchlog_cv_")) / "colonies_annotated.jpg"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), annotated)
    latency = round(time.time() - t0, 2)
    log.info("vision.count_colonies node=M5 count=%d latency=%.2fs", len(best), latency)
    return {
        "count": len(best),
        "annotated_path": str(out_path),
        "method": "OpenCV adaptive threshold + contour area/circularity filter",
        "latency_s": latency,
    }


def first_int(text: str) -> int | None:
    words = {
        "zero": 0, "no": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    }  # fmt: skip
    m = re.search(r"\b(\d+|" + "|".join(words) + r")\b", text.lower())
    if not m:
        return None
    tok = m.group(1)
    return int(tok) if tok.isdigit() else words[tok]


def analyze(
    image_path: str | Path,
    question: str | None = None,
    out_dir: str | Path | None = None,
    colonies: bool | None = None,
) -> dict[str, Any]:
    """Full photo entry: VLM answer, plus OpenCV count when the question is about colonies."""
    t0 = time.time()
    vlm = describe(image_path, question)
    result: dict[str, Any] = {
        "question": question,
        "answer": vlm["answer"],
        "model": vlm["model"],
        "node": "M5",
        "vlm_latency_s": vlm["latency_s"],
    }
    is_count = bool(question and COUNT_RE.search(question))
    if colonies is None:
        colonies = bool(question and COLONY_RE.search(question))
    if is_count:
        result["vlm_count_estimate"] = first_int(vlm["answer"])
    if colonies:
        out = Path(out_dir) / "colonies_annotated.jpg" if out_dir else None
        cv = count_colonies(image_path, out)
        result["opencv"] = cv
        result["vlm_count_estimate"] = first_int(vlm["answer"])
        result["summary"] = (
            f"OpenCV count: {cv['count']} colonies; VLM estimate: "
            f"{result['vlm_count_estimate'] if result['vlm_count_estimate'] is not None else 'n/a'} "
            "(estimate, not exact)."
        )
    elif is_count:
        est = result["vlm_count_estimate"]
        result["summary"] = f"{_one_line(vlm['answer'])} (VLM estimate{'' if est is None else f': {est}'}, not exact)"
    else:
        result["summary"] = _one_line(vlm["answer"])
    result["latency_s"] = round(time.time() - t0, 2)
    return result


def _one_line(text: str, limit: int = 200) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1] + "…"
