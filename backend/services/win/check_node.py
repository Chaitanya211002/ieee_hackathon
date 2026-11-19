"""Smoke test for the WIN node. Builds sample clips, calls every contract endpoint and
writes test_results.md. Needs the node running (run.bat).

    .venv\\Scripts\\python.exe check_node.py                        # node on this laptop
    .venv\\Scripts\\python.exe check_node.py http://192.168.8.20:8001  # over the network

/run_code checks only pass from a client listed in RUN_CODE_CLIENTS (this laptop by default).
The speech clips are synthetic (Windows text-to-speech), so treat the word error rate as a
sanity check. The real numbers come from eval/run_eval.py on the practice pack.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
import requests

BASE = Path(__file__).resolve().parent
SAMPLES = BASE / "samples"
URL = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001").rstrip("/")
SR = 16_000

REFERENCE = (
    "I added the lysis buffer to the first row of the plate and placed the samples "
    "in the centrifuge. The supernatant looks clear, so I will run the gel after lunch."
)


def write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SR and w.getnchannels() == 1 and w.getsampwidth() == 2
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


def make_beeps(seconds: float = 6.0) -> np.ndarray:
    """Three 1 kHz beeps per second-and-a-half, like a bench timer going off."""
    t = np.arange(int(seconds * SR)) / SR
    tone = 0.5 * np.sin(2 * np.pi * 1000 * t)
    gate = ((t % 1.5) < 0.6) & ((t % 0.2) < 0.12)
    return (tone * gate).astype(np.float32)


def make_speech(path: Path) -> bool:
    """Speak REFERENCE into a 16 kHz mono WAV with the built-in Windows voice."""
    if os.name != "nt":
        return False
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, "
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
        "[System.Speech.AudioFormat.AudioChannel]::Mono); "
        f"$s.SetOutputToWaveFile('{path}', $f); "
        f"$s.Speak('{REFERENCE}'); $s.Dispose()"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=60)
        return path.exists() and path.stat().st_size > 1000
    except Exception as exc:  # noqa: BLE001
        print("Could not synthesise speech:", exc)
        return False


def make_encoded_copies(src: Path) -> list[tuple[str, Path]]:
    """Re-encode the speech clip the way phones and browsers actually record it."""
    try:
        import av
    except ImportError:
        return []
    targets = [
        ("Phone voice memo (m4a, AAC)", "note.m4a", "aac", 44100, False),
        ("Browser recording (webm, Opus)", "note.webm", "libopus", 48000, False),
        ("Video clip (mp4, H.264 + AAC)", "clip.mp4", "aac", 44100, True),
    ]
    made = []
    for label, fname, codec, rate, with_video in targets:
        dst = SAMPLES / fname
        try:
            # .m4a is an MP4 container; naming the muxer avoids a Windows-only failure.
            muxer = "mp4" if dst.suffix in (".m4a", ".mp4") else None
            with av.open(str(src)) as inp, av.open(str(dst), "w", format=muxer) as out:
                # Every stream must exist before the first packet is written.
                if with_video:
                    vst = out.add_stream("libx264", rate=5)
                    vst.width, vst.height, vst.pix_fmt = 160, 120, "yuv420p"
                ast = out.add_stream(codec, rate=rate)
                if with_video:
                    seconds = float(inp.duration / av.time_base) if inp.duration else 10.0
                    black = np.zeros((120, 160, 3), dtype=np.uint8)
                    for i in range(int(seconds * 5)):
                        frame = av.VideoFrame.from_ndarray(black, format="rgb24")
                        frame.pts, frame.time_base = i, Fraction(1, 5)
                        for packet in vst.encode(frame):
                            out.mux(packet)
                    for packet in vst.encode(None):
                        out.mux(packet)
                for frame in inp.decode(audio=0):  # keep the decoded timestamps
                    for packet in ast.encode(frame):
                        out.mux(packet)
                for packet in ast.encode(None):
                    out.mux(packet)
            made.append((label, dst))
        except Exception as exc:  # noqa: BLE001 - codec missing from this PyAV build
            print(f"Could not encode {fname}: {exc}")
    return made


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).split()


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def post(endpoint: str, path: Path, **fields) -> dict:
    with open(path, "rb") as fh:
        r = requests.post(
            f"{URL}{endpoint}", files={"file": (path.name, fh)}, data=fields, timeout=600
        )
    r.raise_for_status()
    return r.json()


def run_code(code: str, files: dict[str, bytes] | None = None) -> requests.Response:
    payload = {
        "code": code,
        "files": {k: base64.b64encode(v).decode() for k, v in (files or {}).items()},
    }
    return requests.post(f"{URL}/run_code", json=payload, timeout=120)


def main() -> int:
    SAMPLES.mkdir(exist_ok=True)
    rows: list[str] = []
    failures = 0

    def record(test: str, clip: str, result: str, speed: str, ok: bool) -> None:
        nonlocal failures
        failures += not ok
        rows.append(f"| {test} | {clip} | {result} | {speed} | {'PASS' if ok else 'FAIL'} |")
        print(f"{'PASS' if ok else 'FAIL'}  {test}: {result}")

    health = requests.get(f"{URL}/health", timeout=30).json()
    print("health:", health)
    if health.get("ok") is not True:
        print("Node is not ready.")
        return 1

    beeps = SAMPLES / "timer_beeps.wav"
    write_wav(beeps, make_beeps())
    speech = SAMPLES / "bench_note_tts.wav"
    have_speech = make_speech(speech)

    # 1. /transcribe: contract keys, accuracy, with and without the lab vocabulary hint
    if have_speech:
        for domain in (None, "lab"):
            res = post("/transcribe", speech, **({"domain": domain} if domain else {}))
            shape_ok = (
                isinstance(res["text"], str)
                and isinstance(res["language"], str)
                and all({"start", "end", "text"} <= set(s) for s in res["segments"])
            )
            err = wer(REFERENCE, res["text"])
            record(
                f"Speech to text{' (lab hint)' if domain else ''}",
                speech.name,
                f"WER {err:.1%}, language {res['language']}",
                f"{res['seconds']}s for {res['duration']}s of audio, {res['device']}",
                shape_ok and err <= 0.15,
            )

    # 2. /classify_sound: contract keys, sorted scores, expected event
    sound_cases = [(beeps, "alarm_or_timer")]
    alarm = Path(r"C:\Windows\Media\Alarm01.wav")
    if alarm.exists():
        sound_cases.append((alarm, "alarm_or_timer"))
    for path, expected in sound_cases:
        res = post("/classify_sound", path)
        scores = [x["score"] for x in res["labels"]]
        shape_ok = (
            len(res["labels"]) == 3
            and scores == sorted(scores, reverse=True)
            and all(0 <= s <= 1 for s in scores)
        )
        events = [e["event"] for e in res["lab_events"]]
        top = ", ".join(f"{x['label']} {x['score']}" for x in res["labels"])
        record(
            "Sound identification",
            path.name,
            f"top 3: {top}",
            f"{res['seconds']}s, {res['device']}",
            shape_ok and expected in events,
        )

    # 3. Silence must not produce invented text
    silence = SAMPLES / "silence.wav"
    write_wav(silence, np.zeros(5 * SR, dtype=np.float32))
    res = post("/transcribe", silence)
    record(
        "No speech means no text",
        silence.name,
        f'text: "{res["text"]}"',
        f"{res['seconds']}s",
        res["text"] == "" and res["segments"] == [],
    )

    # 4. Speech and a timer in the same clip
    if have_speech:
        voice = read_wav(speech)
        mix = voice + make_beeps(len(voice) / SR)[: len(voice)] * 0.5
        mixed = SAMPLES / "note_with_timer.wav"
        write_wav(mixed, mix)
        err = wer(REFERENCE, post("/transcribe", mixed)["text"])
        events = [e["event"] for e in post("/classify_sound", mixed)["lab_events"]]
        record(
            "Speech + timer in one clip",
            mixed.name,
            f"WER {err:.1%}; events: {', '.join(events) or 'none'}",
            "-",
            err <= 0.25 and "alarm_or_timer" in events and "speech" in events,
        )

    # 5. The formats phones and browsers really send, including a video file
    if have_speech:
        for label, path in make_encoded_copies(speech):
            res = post("/transcribe", path)
            err = wer(REFERENCE, res["text"])
            record(label, path.name, f"WER {err:.1%}", f"{res['seconds']}s", err <= 0.15)

    # 6. A file that is not audio must be rejected cleanly
    junk = SAMPLES / "not_audio.txt"
    junk.write_text("this is not audio")
    with open(junk, "rb") as fh:
        r = requests.post(f"{URL}/transcribe", files={"file": ("not_audio.txt", fh)}, timeout=60)
    record(
        "Rejects non-audio files",
        junk.name,
        f"HTTP {r.status_code}",
        "-",
        r.status_code in (415, 422),
    )

    # 7. /run_code
    r = run_code("print(6 * 7)")
    if r.status_code == 403:
        record("Code sandbox", "-", "skipped: this client is not in RUN_CODE_CLIENTS", "-", True)
    else:
        res = r.json()
        record(
            "Code runs, stdout captured",
            "print(6 * 7)",
            f"stdout: {res['stdout'].strip()}",
            f"{res['seconds']}s",
            res["exit_code"] == 0 and res["stdout"].strip() == "42" and res["artifacts"] == {},
        )

        csv = b"conc,od\n0,0.05\n1,0.21\n2,0.39\n4,0.80\n8,1.58\n"
        code = (
            "import pandas as pd, numpy as np, matplotlib.pyplot as plt\n"
            "df = pd.read_csv('plate.csv')\n"
            "slope, intercept = np.polyfit(df.conc, df.od, 1)\n"
            "print(f'slope={slope:.3f}')\n"
            "plt.plot(df.conc, df.od, 'o'); plt.plot(df.conc, slope * df.conc + intercept)\n"
            "plt.xlabel('conc'); plt.ylabel('OD'); plt.savefig('standard_curve.png')\n"
        )
        res = run_code(code, {"plate.csv": csv}).json()
        png = base64.b64decode(res["artifacts"].get("standard_curve.png", ""))
        record(
            "Uploaded CSV to plot",
            "plate.csv",
            f"{res['stdout'].strip()}; standard_curve.png {len(png)} bytes",
            f"{res['seconds']}s",
            res["exit_code"] == 0
            and png[:8] == b"\x89PNG\r\n\x1a\n"
            and "slope=0.19" in res["stdout"],
        )

        res = run_code("x = 1 / 0").json()
        record(
            "Errors come back as a traceback",
            "x = 1 / 0",
            f"exit_code {res['exit_code']}",
            f"{res['seconds']}s",
            res["exit_code"] == 1 and "ZeroDivisionError" in res["stderr"],
        )

        res = run_code(
            "import urllib.request\nurllib.request.urlopen('http://example.com', timeout=5)"
        ).json()
        record(
            "No network inside the sandbox",
            "urlopen(example.com)",
            f"exit_code {res['exit_code']}",
            f"{res['seconds']}s",
            res["exit_code"] != 0 and "Error" in res["stderr"],
        )

        timeout_s = health["sandbox"]["timeout_s"]
        res = run_code("while True:\n    pass").json()
        record(
            "Runaway code is stopped",
            "while True: pass",
            f"exit_code {res['exit_code']}; {res['stderr'].strip().splitlines()[-1]}",
            f"{res['seconds']}s",
            res["exit_code"] == -1 and f"Timed out after {timeout_s} s" in res["stderr"],
        )

        r = run_code("print(1)", {"../escape.txt": b"x"})
        record(
            "Rejects unsafe file names",
            "../escape.txt",
            f"HTTP {r.status_code}",
            "-",
            r.status_code == 400,
        )

    sp, gpu = health["speech"], health.get("gpu") or {}
    report = [
        "# WIN node test results",
        "",
        f"- Node: `{URL}`",
        f"- Speech model: {sp['model']} on {sp['device']} ({sp['compute_type']})",
        f"- Sound model: {health['sound']['model']} on {health['sound']['device']}",
        f"- GPU: {gpu.get('name', 'none')} ({gpu.get('vram_total_mb', '?')} MB)",
        f"- Offline mode: {health['offline_mode']}",
        "",
        "| Test | Input | Result | Speed | Status |",
        "|---|---|---|---|---|",
        *rows,
        "",
        "Speech clips are synthetic (Windows text-to-speech); the sound clips are generated "
        "tones or Windows system sounds. These are smoke tests, not accuracy figures.",
        "",
    ]
    (BASE / "test_results.md").write_text("\n".join(report), encoding="utf-8")
    print(f"\n{len(rows) - failures}/{len(rows)} passed. Wrote test_results.md")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
