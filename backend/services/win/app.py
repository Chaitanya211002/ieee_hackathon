"""WIN node service for BenchLog (contract: docs/win-service-contract.md).

Runs on the Windows laptop (i9-12900H, RTX 3060 6 GB). Three jobs, all local:

  POST /transcribe      speech -> text      Whisper large-v3-turbo, faster-whisper on CUDA
  POST /classify_sound  sound labels        AST AudioSet classifier on the CPU
  POST /run_code        run analysis code   separate venv, temp dir, timeout, no network
  GET  /health          {"ok": true}

From the repo root:

    uvicorn backend.services.win.app:app --host 0.0.0.0 --port 8001

or double-click backend/services/win/run.bat. Uploads are decoded in memory and
never written to disk; sandbox temp dirs are deleted after every run.
"""

from __future__ import annotations

import base64
import binascii
import io
import logging
import os
import re
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np

WIN_DIR = Path(__file__).resolve().parent
MODELS_DIR = Path(os.environ.get("WIN_MODELS_DIR", WIN_DIR / "models"))
# Must be set before huggingface_hub / transformers are imported.
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "hf"))

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from backend.config import get_config  # noqa: E402  (also forces HF offline mode)

log = logging.getLogger("benchlog.win")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ----------------------------------------------------------------------------
# Configuration: backend/config.yaml first, environment variables override.
# ----------------------------------------------------------------------------
_cfg = get_config()
NODE = "WIN"
SOUND_MODEL = os.environ.get("SOUND_MODEL", _cfg["models"]["sound"])
# config.yaml's models.whisper is the MLX build for the Mac; this node needs the
# faster-whisper name. Add models.whisper_win to config.yaml to change it.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", _cfg["models"].get("whisper_win", "large-v3-turbo"))
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")  # auto | cuda | cpu
RUN_TIMEOUT_S = int(_cfg.get("sandbox", {}).get("timeout_s", 20))
OFFLINE = os.environ.get("HF_HUB_OFFLINE", "") == "1"

SAMPLE_RATE = 16_000
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "200")) * 1024 * 1024
MAX_AUDIO_SECONDS = int(os.environ.get("MAX_AUDIO_SECONDS", "900"))
WINDOW_S, HOP_S = 10.0, 5.0  # AST was trained on 10-second clips
LABEL_FLOOR = 0.10  # a label counts as present in a window above this score
EVENT_FLOOR = 0.20  # a lab event is reported above this score

# /run_code executes whatever it is sent, so it only answers these client IPs.
# Loopback only by default; set RUN_CODE_CLIENTS to the M5's IP (or * for any).
RUN_CODE_CLIENTS = {
    c.strip() for c in os.environ.get("RUN_CODE_CLIENTS", "127.0.0.1,::1").split(",") if c.strip()
}
_SCRIPTS = "Scripts" if os.name == "nt" else "bin"
_PY = "python.exe" if os.name == "nt" else "python"
SANDBOX_PYTHON = Path(os.environ.get("SANDBOX_PYTHON", WIN_DIR / "sandbox_venv" / _SCRIPTS / _PY))
SANDBOX_ROOT = SANDBOX_PYTHON.parent.parent
MAX_OUTPUT_CHARS = 200_000
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024

# Vocabulary hint for Whisper, used only when the caller sends domain=lab.
LAB_PROMPT = (
    "Wet-lab bench notes: pipette, micropipette, microliters, milliliters, centrifuge, "
    "supernatant, pellet, vortex, incubate, PCR, qPCR, agarose gel, electrophoresis, "
    "ELISA, lysis buffer, PBS, Tris, EDTA, ethanol, aliquot, Eppendorf tube, 96-well plate, "
    "plate reader, absorbance, optical density, serial dilution, Western blot."
)

# AudioSet has no "centrifuge" or "freezer alarm" class, so lab events are a keyword
# mapping over its 527 general labels. A heuristic, returned as an extra field.
LAB_EVENTS = [
    {
        "event": "alarm_or_timer",
        "description": "Instrument alarm, timer or beeper",
        # Pure-tone beepers are often labelled "Dial tone" or "Busy signal".
        "keywords": [
            "alarm",
            "beep",
            "bleep",
            "buzzer",
            "siren",
            "ding",
            "bell",
            "chime",
            "sine wave",
            "ringtone",
            "smoke detector",
            "telephone",
            "dial tone",
            "busy signal",
        ],
    },
    {
        "event": "glass_break",
        "description": "Glass breaking or glassware knocked over",
        "keywords": ["glass", "shatter", "smash", "crash", "breaking"],
    },
    {
        "event": "liquid_handling",
        "description": "Pouring, dripping or running liquid",
        "keywords": [
            "pour",
            "liquid",
            "drip",
            "water",
            "splash",
            "trickle",
            "gurgling",
            "fill",
            "spray",
            "sink",
            "faucet",
        ],
    },
    {
        "event": "equipment_running",
        "description": "Motorised equipment running (centrifuge, fan, pump, shaker)",
        "keywords": [
            "mechanical fan",
            "hum",
            "whir",
            "engine",
            "motor",
            "air conditioning",
            "vacuum cleaner",
            "blender",
            "mechanisms",
            "drill",
            "vibration",
            "white noise",
            "pink noise",
            "static",
        ],
    },
    {
        "event": "door_or_impact",
        "description": "Door, drawer or something dropped",
        "keywords": ["door", "slam", "knock", "thump", "thud", "bang", "drawer", "cupboard"],
    },
    {
        "event": "speech",
        "description": "Someone speaking",
        "keywords": ["speech", "conversation", "narration", "monologue"],
    },
]

# ----------------------------------------------------------------------------
# Model loading
# ----------------------------------------------------------------------------
STATE: dict = {"whisper": None, "sound": None, "started": time.time()}
_whisper_lock = threading.Lock()
_sound_lock = threading.Lock()
_run_lock = threading.Lock()


def _add_nvidia_dll_dirs() -> None:
    """Let Windows find the cuBLAS / cuDNN DLLs that pip installed."""
    if os.name != "nt":
        return
    site = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
    for bin_dir in site.glob("*/bin"):
        try:
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
        except OSError as exc:  # pragma: no cover - Windows only
            log.warning("Could not add DLL directory %s: %s", bin_dir, exc)


def load_whisper() -> dict:
    """Load Whisper on CUDA; fall back to CPU int8 if the GPU setup fails."""
    _add_nvidia_dll_dirs()
    from faster_whisper import WhisperModel

    attempts = [("cuda", "float16"), ("cuda", "int8_float16"), ("cpu", "int8")]
    if WHISPER_DEVICE == "cpu":
        attempts = [("cpu", "int8")]
    elif WHISPER_DEVICE == "cuda":
        attempts = attempts[:2]

    errors: list[str] = []
    for device, compute_type in attempts:
        try:
            t0 = time.time()
            model = WhisperModel(
                WHISPER_MODEL,
                device=device,
                compute_type=compute_type,
                download_root=str(MODELS_DIR / "whisper"),
                local_files_only=OFFLINE,
            )
            # Missing GPU libraries only show up on the first real inference.
            segments, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), beam_size=1)
            list(segments)
            log.info(
                "Whisper %s ready on %s (%s) in %.1fs",
                WHISPER_MODEL,
                device,
                compute_type,
                time.time() - t0,
            )
            return {
                "model": model,
                "name": WHISPER_MODEL,
                "device": device,
                "compute_type": compute_type,
                "fallback_errors": errors,
            }
        except Exception as exc:  # noqa: BLE001 - keep every failure reason for /health
            msg = f"{device}/{compute_type}: {type(exc).__name__}: {exc}"
            log.warning("Whisper load failed on %s", msg)
            errors.append(msg)
    raise RuntimeError("Whisper could not be loaded: " + " | ".join(errors))


def load_sound_model() -> dict:
    """Load the AST classifier on the CPU, which keeps GPU memory for Whisper and Ollama."""
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification

    t0 = time.time()
    extractor = ASTFeatureExtractor.from_pretrained(SOUND_MODEL)
    model = ASTForAudioClassification.from_pretrained(SOUND_MODEL).eval()
    torch.set_num_threads(max(1, min(8, os.cpu_count() or 4)))
    labels = [model.config.id2label[i] for i in range(model.config.num_labels)]
    log.info("Sound model ready on cpu (%d classes) in %.1fs", len(labels), time.time() - t0)
    return {
        "model": model,
        "extractor": extractor,
        "labels": labels,
        "name": SOUND_MODEL,
        "device": "cpu",
    }


@asynccontextmanager
async def lifespan(_: FastAPI):
    if os.environ.get("WIN_SKIP_MODEL_LOAD") != "1":  # tests inject stand-ins
        STATE["whisper"] = load_whisper()
        STATE["sound"] = load_sound_model()
    yield


app = FastAPI(title="BenchLog WIN node", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ----------------------------------------------------------------------------
# Audio helpers
# ----------------------------------------------------------------------------
def read_upload(upload: UploadFile) -> np.ndarray:
    """Decode an audio or video upload to 16 kHz mono float32, in memory."""
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than the upload limit")
    from faster_whisper import decode_audio

    try:
        audio = decode_audio(io.BytesIO(data), sampling_rate=SAMPLE_RATE)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=415, detail=f"Could not decode audio from this file: {exc}"
        ) from exc
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0:
        raise HTTPException(status_code=422, detail="No audio track found in this file")
    if audio.size / SAMPLE_RATE > MAX_AUDIO_SECONDS:
        raise HTTPException(
            status_code=413,
            detail=f"Audio is {audio.size / SAMPLE_RATE:.0f}s; the limit is {MAX_AUDIO_SECONDS}s",
        )
    return audio


def window_starts(n_samples: int) -> list[int]:
    win, hop = int(WINDOW_S * SAMPLE_RATE), int(HOP_S * SAMPLE_RATE)
    if n_samples <= win:
        return [0]
    return list(range(0, n_samples - win + hop, hop))


def map_lab_events(label_scores: dict[str, float], first_seen: dict[str, float]) -> list[dict]:
    events = []
    for spec in LAB_EVENTS:
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(k) for k in spec["keywords"]) + r")\b", re.IGNORECASE
        )
        hits = {
            lab: sc for lab, sc in label_scores.items() if sc >= LABEL_FLOOR and pattern.search(lab)
        }
        if not hits or max(hits.values()) < EVENT_FLOOR:
            continue
        evidence = sorted(hits, key=hits.get, reverse=True)[:4]
        events.append(
            {
                "event": spec["event"],
                "description": spec["description"],
                "score": round(max(hits.values()), 3),
                "evidence": evidence,
                "first_seen_s": min(first_seen[lab] for lab in evidence),
            }
        )
    return sorted(events, key=lambda e: e["score"], reverse=True)


def classify_audio(audio: np.ndarray, top_k: int) -> dict:
    import torch

    sound = STATE["sound"]
    if sound is None:
        raise HTTPException(status_code=503, detail="Sound model is not loaded")
    win = int(WINDOW_S * SAMPLE_RATE)
    starts = window_starts(audio.size)
    chunks = [audio[s : s + win] for s in starts]

    t0 = time.time()
    batches = []
    with _sound_lock, torch.inference_mode():
        for i in range(0, len(chunks), 8):
            inputs = sound["extractor"](
                chunks[i : i + 8], sampling_rate=SAMPLE_RATE, return_tensors="pt"
            )
            logits = sound["model"](**inputs).logits
            batches.append(torch.sigmoid(logits).cpu().numpy())  # AudioSet is multi-label
    probs = np.concatenate(batches, axis=0)
    labels = sound["labels"]

    best = probs.max(axis=0)  # a clip's score for a label is its best window
    label_scores = {labels[i]: float(best[i]) for i in range(len(labels))}
    first_seen = {}
    for i, lab in enumerate(labels):
        present = np.nonzero(probs[:, i] >= LABEL_FLOOR)[0]
        idx = int(present[0]) if present.size else int(np.argmax(probs[:, i]))
        first_seen[lab] = round(starts[idx] / SAMPLE_RATE, 2)

    order = np.argsort(best)[::-1][:top_k]
    seconds = round(time.time() - t0, 2)
    log.info("classify_sound node=%s windows=%d latency=%.2fs", NODE, len(starts), seconds)
    return {
        "labels": [{"label": labels[i], "score": round(float(best[i]), 3)} for i in order],
        "lab_events": map_lab_events(label_scores, first_seen),
        "duration": round(audio.size / SAMPLE_RATE, 2),
        "node": NODE,
        "device": sound["device"],
        "seconds": seconds,
    }


def transcribe_audio(
    audio: np.ndarray, language: str | None, task: str, domain: str | None, prompt: str | None
) -> dict:
    whisper = STATE["whisper"]
    if whisper is None:
        raise HTTPException(status_code=503, detail="Speech model is not loaded")
    if task not in ("transcribe", "translate"):
        raise HTTPException(status_code=400, detail="task must be 'transcribe' or 'translate'")
    initial_prompt = prompt or (LAB_PROMPT if (domain or "").lower() == "lab" else None)

    t0 = time.time()
    with _whisper_lock:
        segments, info = whisper["model"].transcribe(
            audio,
            language=language or None,
            task=task,
            beam_size=5,
            vad_filter=True,  # skips silence, which stops Whisper inventing text
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
        )
        segs = [
            {
                "start": round(float(s.start), 2),
                "end": round(float(s.end), 2),
                "text": s.text.strip(),
            }
            for s in segments
        ]
    seconds = round(time.time() - t0, 2)
    log.info("transcribe node=%s device=%s latency=%.2fs", NODE, whisper["device"], seconds)
    return {
        "text": " ".join(s["text"] for s in segs).strip(),
        "segments": segs,
        "language": info.language,
        "language_probability": round(float(info.language_probability), 3),
        "duration": round(audio.size / SAMPLE_RATE, 2),
        "node": NODE,
        "device": whisper["device"],
        "seconds": seconds,
    }


# ----------------------------------------------------------------------------
# Code sandbox
# ----------------------------------------------------------------------------
class RunCodeRequest(BaseModel):
    code: str
    files: dict[str, str] = Field(default_factory=dict)  # name -> base64


def _sandbox_env(tmp: Path) -> dict[str, str]:
    """A minimal environment: nothing inherited except what Windows needs to start Python."""
    env = {
        "MPLBACKEND": "Agg",
        # Persistent, so matplotlib's font cache is not rebuilt (seconds) on every run.
        "MPLCONFIGDIR": str(SANDBOX_ROOT / ".mplconfig"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "BENCHLOG_SANDBOX": "1",
        # Belt and braces with sandbox_guard.py: dead proxies make HTTP fail fast.
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "http_proxy": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "TEMP": str(tmp),
        "TMP": str(tmp),
        "TMPDIR": str(tmp),
        "HOME": str(tmp),
        "USERPROFILE": str(tmp),
        "APPDATA": str(tmp),
        "LOCALAPPDATA": str(tmp),
    }
    for key in (
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
    ):
        if key in os.environ:
            env[key] = os.environ[key]
    system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
    env["PATH"] = (
        os.pathsep.join([str(Path(system_root) / "System32"), system_root])
        if os.name == "nt"
        else "/usr/bin:/bin"
    )
    return env


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, check=False
        )
    else:  # pragma: no cover - the service targets Windows
        import signal

        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(text) - MAX_OUTPUT_CHARS} more chars]"


def run_sandboxed(code: str, files: dict[str, str]) -> dict:
    if not SANDBOX_PYTHON.exists():
        raise HTTPException(status_code=503, detail="Sandbox venv is missing; run setup.bat")
    decoded: dict[str, bytes] = {}
    for name, payload in files.items():
        if Path(name).name != name or name in ("", ".", "..", "main.py"):
            raise HTTPException(status_code=400, detail=f"Invalid file name: {name!r}")
        try:
            decoded[name] = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{name}: not valid base64") from exc

    t0 = time.time()
    with _run_lock, tempfile.TemporaryDirectory(prefix="benchlog_run_") as tmp_name:
        tmp = Path(tmp_name)
        for name, data in decoded.items():
            (tmp / name).write_bytes(data)
        (tmp / "main.py").write_text(code, encoding="utf-8")

        kwargs: dict = (
            {"creationflags": subprocess.CREATE_NO_WINDOW}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        proc = subprocess.Popen(
            # -I: isolated mode, ignores PYTHON* variables and the user site directory.
            [str(SANDBOX_PYTHON), "-I", "-X", "utf8", "main.py"],
            cwd=tmp,
            env=_sandbox_env(tmp),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )
        try:
            out, err = proc.communicate(timeout=RUN_TIMEOUT_S)
            exit_code = proc.returncode
            stderr = err.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            out, err = proc.communicate()
            exit_code = -1
            partial = err.decode("utf-8", "replace").rstrip()
            stderr = (partial + "\n" if partial else "") + f"Timed out after {RUN_TIMEOUT_S} s"

        artifacts: dict[str, str] = {}
        total = 0
        for png in sorted(tmp.glob("*.png")):
            total += png.stat().st_size
            if total > MAX_ARTIFACT_BYTES:
                stderr += f"\n[artifact {png.name} dropped: over the artifact size limit]"
                continue
            artifacts[png.name] = base64.b64encode(png.read_bytes()).decode("ascii")

    seconds = round(time.time() - t0, 2)
    log.info(
        "run_code node=%s exit_code=%s artifacts=%d latency=%.2fs",
        NODE,
        exit_code,
        len(artifacts),
        seconds,
    )
    return {
        "stdout": _clip(out.decode("utf-8", "replace")),
        "stderr": _clip(stderr),
        "exit_code": exit_code,
        "artifacts": artifacts,
        "node": NODE,
        "seconds": seconds,
    }


def _network_block_installed() -> bool:
    site_packages = "Lib/site-packages" if os.name == "nt" else "lib/python*/site-packages"
    return any(SANDBOX_ROOT.glob(f"{site_packages}/benchlog_sandbox.pth"))


_gpu_cache: dict = {"at": 0.0, "value": None}


def gpu_info() -> dict | None:
    """GPU name and memory, cached for 30 s because /health is polled every few seconds."""
    if time.time() - _gpu_cache["at"] < 30:
        return _gpu_cache["value"]
    _gpu_cache.update(at=time.time(), value=_query_gpu())
    return _gpu_cache["value"]


def _query_gpu() -> dict | None:
    try:
        out = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            .stdout.strip()
            .splitlines()[0]
        )
        name, total, used = [x.strip() for x in out.split(",")]
        return {"name": name, "vram_total_mb": int(total), "vram_used_mb": int(used)}
    except Exception:  # noqa: BLE001 - no GPU, or nvidia-smi missing
        return None


# ----------------------------------------------------------------------------
# Endpoints (docs/win-service-contract.md). Extra response keys are additive.
# ----------------------------------------------------------------------------
@app.get("/health")
def health() -> dict:
    w, s = STATE["whisper"], STATE["sound"]
    return {
        "ok": bool(w and s),
        "node": NODE,
        "offline_mode": OFFLINE,
        "speech": None
        if not w
        else {
            "model": w["name"],
            "device": w["device"],
            "compute_type": w["compute_type"],
            "fallback_errors": w["fallback_errors"],
        },
        "sound": None if not s else {"model": s["name"], "device": s["device"]},
        "sandbox": {
            "ready": SANDBOX_PYTHON.exists(),
            "network_block": _network_block_installed(),
            "timeout_s": RUN_TIMEOUT_S,
            "allowed_clients": sorted(RUN_CODE_CLIENTS),
        },
        "gpu": gpu_info(),
        "python": sys.version.split()[0],
        "uptime_s": round(time.time() - STATE["started"]),
    }


@app.post("/transcribe")
def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(default=None),
    task: str = Form(default="transcribe"),
    domain: str | None = Form(default=None),
    prompt: str | None = Form(default=None),
) -> dict:
    """-> {"text", "segments": [{"start", "end", "text"}], "language"}"""
    return transcribe_audio(read_upload(file), language, task, domain, prompt)


@app.post("/classify_sound")
def classify_sound(file: UploadFile = File(...), top_k: int = Form(default=3)) -> dict:
    """-> {"labels": [{"label", "score"}]} sorted by score, descending."""
    return classify_audio(read_upload(file), max(1, min(top_k, 20)))


@app.post("/run_code")
def run_code(body: RunCodeRequest, request: Request) -> dict:
    """-> {"stdout", "stderr", "exit_code", "artifacts": {name: base64 png}}"""
    client = request.client.host if request.client else ""
    if "*" not in RUN_CODE_CLIENTS and client not in RUN_CODE_CLIENTS:
        raise HTTPException(
            status_code=403,
            detail=f"/run_code is not enabled for {client}. Add it to RUN_CODE_CLIENTS in run.bat.",
        )
    return run_sandboxed(body.code, body.files)
