"""Video pipeline: ffmpeg frames -> Qwen3-VL as one ordered sequence; audio track -> audio pipeline.

Frames: video.fps (1 fps), at most video.max_frames, long side <= video.max_side. With
video.adaptive_fps, a clip shorter than max_frames seconds is sampled more densely so it still
yields max_frames frames. Samples are spread evenly from the first frame to the last, because
questions often ask about the start and the end. If the file has an audio track it is
extracted as 16 kHz mono WAV and sent through the audio pipeline; both are merged into one result.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from backend import nodes
from backend.config import get_config
from backend.pipelines import audio

log = logging.getLogger("benchlog.video")

SYSTEM_PROMPT = (
    "You are the vision assistant in BenchLog, a lab notebook. You are given frames sampled in time "
    "order from one short video, each labelled with its timestamp. Treat them as a sequence: track "
    "objects across frames to work out motion, direction, order of appearance, changes in text, "
    "colour, size or count, and what is there at the start versus the end. Answer the question "
    "directly in the first sentence, then give the evidence in one short sentence citing frame numbers. "
    "Give counts as digits."
)
DESCRIBE_PROMPT = "Describe what happens in this video, in order, in 2-3 sentences."


def probe(video_path: str | Path) -> dict[str, Any]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
         "-of", "json", str(video_path)],
        capture_output=True, check=True, text=True,
    ).stdout  # fmt: skip
    info = json.loads(out)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "duration": float(info.get("format", {}).get("duration") or 0),
        "width": v.get("width"),
        "height": v.get("height"),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def frame_times(duration: float) -> list[float]:
    cfg = get_config()["video"]
    max_frames = int(cfg["max_frames"])
    if duration <= 0:
        return [0.0]
    n = max_frames if cfg.get("adaptive_fps") else min(max_frames, max(1, math.floor(duration * cfg["fps"])))
    n = min(n, max_frames)
    end = max(0.0, duration - 0.05)  # last decodable instant
    if n == 1:
        return [0.0]
    return [round(end * i / (n - 1), 2) for i in range(n)]


def extract_frames(video_path: str | Path, out_dir: str | Path) -> list[dict[str, Any]]:
    cfg = get_config()["video"]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    info = probe(video_path)
    side = int(cfg["max_side"])
    scale = f"scale='if(gt(iw,ih),min({side},iw),-2)':'if(gt(iw,ih),-2,min({side},ih))'"
    frames = []
    for i, t in enumerate(frame_times(info["duration"])):
        dest = out_dir / f"frame_{i:02d}.jpg"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{t}", "-i", str(video_path),
             "-frames:v", "1", "-vf", scale, "-q:v", "3", str(dest)],
            check=True,
        )  # fmt: skip
        if dest.exists():
            frames.append({"index": i, "t": t, "path": str(dest)})
    return frames


def extract_audio(video_path: str | Path, out_dir: str | Path) -> Path | None:
    dest = Path(out_dir) / "audio.wav"
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(dest)],
        capture_output=True,
    )  # fmt: skip
    return dest if r.returncode == 0 and dest.exists() and dest.stat().st_size > 1000 else None


def contact_sheets(frames: list[dict[str, Any]], per_sheet: int, cols: int) -> list[bytes]:
    """Tile frames, in order, into JPEG sheets; each tile is labelled with its frame number and time.

    Ollama resizes every image to a fixed ~1k-token resolution, so 10 separate frames cost 10x
    the prefill of one image. Sheets keep the order and timestamps at a fraction of the cost.
    """
    import cv2
    import numpy as np

    sheets = []
    for start in range(0, len(frames), per_sheet):
        group = frames[start : start + per_sheet]
        imgs = [cv2.imread(f["path"]) for f in group]
        h, w = imgs[0].shape[:2]
        c = min(cols, len(imgs))
        rows = math.ceil(len(imgs) / c)
        pad = 6
        sheet = np.full((rows * (h + pad) + pad, c * (w + pad) + pad, 3), 255, np.uint8)
        for k, (f, img) in enumerate(zip(group, imgs)):
            img = cv2.resize(img, (w, h))
            r, col = divmod(k, c)
            y, x = pad + r * (h + pad), pad + col * (w + pad)
            sheet[y : y + h, x : x + w] = img
            label = f"#{f['index'] + 1}  {f['t']:.1f}s"
            scale = max(0.6, w / 500)
            cv2.rectangle(sheet, (x, y), (x + int(170 * scale), y + int(34 * scale)), (0, 0, 0), -1)
            cv2.putText(sheet, label, (x + 6, y + int(25 * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.8 * scale,
                        (255, 255, 255), 2)  # fmt: skip
        ok, buf = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, 90])
        sheets.append(buf.tobytes())
    return sheets


def ask_frames(frames: list[dict[str, Any]], question: str | None) -> dict[str, Any]:
    cfg = get_config()
    vcfg = cfg["video"]
    model = cfg["models"]["vision"]
    q = question.strip() if question and question.strip() else DESCRIBE_PROMPT
    listing = ", ".join(f"#{f['index'] + 1} at {f['t']:.1f}s" for f in frames)
    if vcfg.get("mode", "sheets") == "sheets":
        per, cols = int(vcfg.get("frames_per_sheet", 5)), int(vcfg.get("sheet_cols", 5))
        images = [base64.b64encode(b).decode("ascii") for b in contact_sheets(frames, per, cols)]
        prompt = (
            f"{len(frames)} frames sampled in time order ({listing}), tiled left to right, top to bottom, "
            f"across {len(images)} image(s); each tile is labelled with its frame number and time. "
            f"Read the tiles in order as one video.\n\n{q}"
        )
    else:
        images = [base64.b64encode(Path(f["path"]).read_bytes()).decode("ascii") for f in frames]
        prompt = f"{len(frames)} frames in time order: {listing}.\n\n{q}"
    t0 = time.time()
    answer = nodes.chat(
        "m5",
        model,
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt, "images": images}],
    )
    latency = round(time.time() - t0, 2)
    log.info("video.ask_frames node=M5 mode=%s frames=%d images=%d latency=%.2fs",
             vcfg.get("mode", "sheets"), len(frames), len(images), latency)  # fmt: skip
    return {"answer": answer, "model": model, "latency_s": latency, "images_sent": len(images)}


def analyze(video_path: str | Path, question: str | None = None, out_dir: str | Path | None = None) -> dict[str, Any]:
    """Full video entry: ordered-frame VLM answer + audio pipeline on the soundtrack (if any)."""
    t0 = time.time()
    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="benchlog_video_"))
    info = probe(video_path)
    frames = extract_frames(video_path, out)
    vlm = ask_frames(frames, question)
    result: dict[str, Any] = {
        "question": question,
        "answer": vlm["answer"],
        "frames": frames,
        "duration_s": round(info["duration"], 2),
        "model": vlm["model"],
        "vlm_latency_s": vlm["latency_s"],
        "node": "M5",
        "audio": None,
    }
    if info["has_audio"]:
        wav = extract_audio(video_path, out)
        if wav:
            a = audio.analyze(wav)
            result["audio"] = {k: a[k] for k in ("transcript", "segments", "sound_labels", "sound_alerts",
                                                 "summary", "transcribe_node", "classify_node", "latency_s")}  # fmt: skip
    summary = " ".join(vlm["answer"].split())
    summary = summary if len(summary) <= 200 else summary[:199] + "…"
    if result["audio"] and result["audio"]["transcript"]:
        summary += f' · Audio: "{result["audio"]["transcript"][:100]}"'
    elif result["audio"] and result["audio"]["sound_alerts"]:
        summary += " · Sounds: " + ", ".join(a["label"] for a in result["audio"]["sound_alerts"])
    result["summary"] = summary
    result["latency_s"] = round(time.time() - t0, 2)
    return result
