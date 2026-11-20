"""Image pipeline: Qwen3-VL description / Q&A, plus an OpenCV colony count for plates.

Pure functions: an image path (and optional question) in, a dict out. The VLM always runs on
the M5. VLMs are unreliable counters, so for colony questions the OpenCV blob count is
returned alongside the VLM estimate and the VLM number is labelled an estimate.

Fine detail (a burette meniscus, a label, a display) is lost when a 12 MP phone photo is shrunk
to vision.max_side, so a question about a reading, a label or other fine detail first gets a
"where should I look" pass: the model boxes the feature that decides the answer, that region is
cut from the full-resolution original, and the answer call sees both the whole photo and the
enlarged crop (vision.zoom in config.yaml).
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
    "When asked for a reading on a graduated scale (burette, pipette, cylinder, ruler, thermometer), "
    "first find the numbered marks just above and just below the level or pointer, then estimate "
    "between them; if the photo is too blurry or angled for the last digit, give the two marks and "
    "an approximate value and say it is approximate. "
    "If something is not visible or cannot be determined, say so instead of guessing."
)
DESCRIBE_PROMPT = (
    "Describe this image for a lab notebook entry in 2-3 sentences: what it shows, any visible "
    "text or labels, and anything notable (contamination, bands, colonies, readings)."
)

LOCATE_PROMPT = (
    'Do not answer yet. Question: "{q}"\n'
    "First name, in a few words, the single visual feature that decides the answer (for example: "
    "the liquid surface in the tube, the printed capacity, the display digits). Then give its "
    'bounding box. Reply with only JSON: {{"feature": "<feature>", "bbox_2d": [x1, y1, x2, y2]}}'
)
ZOOM_NOTE = (
    "The second image is an enlarged crop of one part of the first image, so that fine detail there is readable. "
    "It does not show everything: use the first image for anything outside the crop.\n"
)
BBOX_RE = re.compile(
    r"\[\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\]"
)

# Questions about fine detail, where the answer sits in a small part of the photo. Only these get
# the look-closer pass: it costs an extra model call, and "what colour is it" does not need it.
DETAIL_RE = re.compile(
    r"\b(read|reads|reading|scale|marks?|markings?|graduations?|level|meniscus|gauge|dial|displays?|displayed|"
    r"screen|labels?|labelled|labeled|text|words?|written|printed|says?|value|numbers?|digits?|how much|"
    r"volume|capacity|temperature|weight|mass|time|date|lot|batch|expiry|expires|expiration|concentration|"
    r"ph|serial|barcode)\b",
    re.I,
)
COUNT_RE = re.compile(r"\b(how many|count|number of)\b", re.I)
COLONY_RE = re.compile(r"\b(colon(y|ies)|cfu|plate|petri|agar|blobs?)\b", re.I)


def _read(image_path: str | Path) -> np.ndarray:
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"could not read image {image_path}")
    return img


def _encode(image: str | Path | np.ndarray, max_side: int) -> str:
    img = image if isinstance(image, np.ndarray) else _read(image)
    h, w = img.shape[:2]
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("could not encode image")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def thread_messages(
    system: str, images: list[str], question: str, history: list[dict[str, str]] | None
) -> list[dict[str, Any]]:
    """Chat messages for a question about media, with earlier Q&A turns (follow-ups) in between.

    The media is attached to the first user turn only, so a follow-up costs no extra image tokens
    beyond the original question.
    """
    turns = [*(history or []), {"question": question, "answer": None}]
    msgs: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for i, t in enumerate(turns):
        user: dict[str, Any] = {"role": "user", "content": t["question"]}
        if i == 0:
            user["images"] = images
        msgs.append(user)
        if t["answer"] is not None:
            msgs.append({"role": "assistant", "content": t["answer"]})
    return msgs


def parse_bbox(text: str) -> tuple[float, float, float, float] | None:
    """Box from the model's reply as fractions of the image (x1, y1, x2, y2), or None.

    Qwen3-VL answers in a 0-1000 grid whatever the image size.
    """
    m = BBOX_RE.search(text or "")
    if not m:
        return None
    x1, y1, x2, y2 = (float(v) / 1000 for v in m.groups())
    x1, x2 = sorted((min(max(x1, 0.0), 1.0), min(max(x2, 0.0), 1.0)))
    y1, y2 = sorted((min(max(y1, 0.0), 1.0), min(max(y2, 0.0), 1.0)))
    if x2 - x1 < 0.005 or y2 - y1 < 0.005:
        return None
    return x1, y1, x2, y2


def crop_box(box: tuple[float, float, float, float], zoom: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Widen the model's box by a margin; None when the result covers most of the image anyway."""
    x1, y1, x2, y2 = box
    margin, min_margin = zoom.get("margin", 0.5), zoom.get("min_margin", 0.08)
    mx = max((x2 - x1) * margin, min_margin)
    my = max((y2 - y1) * margin, min_margin)
    x1, y1, x2, y2 = max(0.0, x1 - mx), max(0.0, y1 - my), min(1.0, x2 + mx), min(1.0, y2 + my)
    if (x2 - x1) * (y2 - y1) > zoom.get("max_area_frac", 0.5):
        return None
    return x1, y1, x2, y2


def locate(img: np.ndarray, img_b64: str, question: str) -> dict[str, Any] | None:
    """Ask the model where to look, and cut that region from the full-resolution image.

    Returns {"box", "crop" (ndarray), "latency_s"} or None when there is nothing to zoom into.
    Uses the same system prompt and image as the answer call, so Ollama reuses its cached image
    tokens for the second call.
    """
    cfg = get_config()
    zoom = cfg["vision"].get("zoom") or {}
    if not zoom.get("enabled"):
        return None
    t0 = time.time()
    try:
        reply = nodes.chat(
            "m5",
            cfg["models"]["vision"],
            thread_messages(SYSTEM_PROMPT, [img_b64], LOCATE_PROMPT.format(q=question), None),
        )
    except Exception as exc:  # noqa: BLE001 - zooming is an extra; the plain answer still works
        log.warning("vision.locate failed: %s", exc)
        return None
    box = parse_bbox(reply)
    box = crop_box(box, zoom) if box else None
    latency = round(time.time() - t0, 2)
    log.info("vision.locate node=M5 box=%s latency=%.2fs", box and [round(v, 3) for v in box], latency)
    if box is None:
        return None
    h, w = img.shape[:2]
    crop = img[int(box[1] * h) : int(box[3] * h), int(box[0] * w) : int(box[2] * w)]
    if crop.size == 0:
        return None
    return {"box": [round(v, 4) for v in box], "crop": crop, "latency_s": latency}


def describe(
    image_path: str | Path,
    question: str | None = None,
    history: list[dict[str, str]] | None = None,
    zoom: bool = True,
) -> dict[str, Any]:
    """Ask Qwen3-VL about one image. `history` holds earlier {"question", "answer"} turns about it.

    For a question about fine detail (DETAIL_RE) the model first says where to look and gets
    that region enlarged from the full-resolution photo as a second image, unless `zoom` is off.
    Returns {"answer", "question", "node", "latency_s", "model"} plus "zoom" {"box", "crop",
    "latency_s"} when a crop was used.
    """
    cfg = get_config()
    model = cfg["models"]["vision"]
    max_side = cfg["vision"]["max_side"]
    full = _read(image_path)
    img = _encode(full, max_side)
    asked = question.strip() if question and question.strip() else None
    t0 = time.time()
    found = locate(full, img, asked) if asked and zoom and DETAIL_RE.search(asked) else None
    msgs = thread_messages(SYSTEM_PROMPT, [img], asked or DESCRIBE_PROMPT, history)
    if found:
        last = msgs[-1]
        last["images"] = [*last.get("images", []), _encode(found["crop"], max_side)]
        last["content"] = ZOOM_NOTE + last["content"]
    answer = nodes.chat("m5", model, msgs)
    latency = round(time.time() - t0, 2)
    log.info("vision.describe node=M5 zoom=%s latency=%.2fs", bool(found), latency)
    out = {"answer": answer, "question": question, "model": model, "node": "M5", "latency_s": latency}
    if found:
        out["zoom"] = found
    return out


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
            if inside.size and (inside > 0).mean() >= c["min_fill"]:
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
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Full photo entry: VLM answer, plus OpenCV count when the question is about colonies.

    `history` makes this a follow-up: earlier {"question", "answer"} turns about the same image.
    """
    t0 = time.time()
    is_count = bool(question and COUNT_RE.search(question))
    if colonies is None:
        colonies = bool(question and COLONY_RE.search(question))
    # Counting needs the whole image; zooming into one part would hide the rest.
    vlm = describe(image_path, question, history, zoom=not (is_count or colonies))
    result: dict[str, Any] = {
        "question": question,
        "answer": vlm["answer"],
        "model": vlm["model"],
        "node": "M5",
        "vlm_latency_s": vlm["latency_s"],
    }
    if "zoom" in vlm:
        crop_path = Path(out_dir or tempfile.mkdtemp(prefix="benchlog_zoom_")) / "zoom_crop.jpg"
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(crop_path), vlm["zoom"]["crop"])
        result["zoom"] = {"box": vlm["zoom"]["box"], "crop_path": str(crop_path), "latency_s": vlm["zoom"]["latency_s"]}
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
