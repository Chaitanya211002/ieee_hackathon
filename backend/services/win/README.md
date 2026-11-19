# WIN node service

The Windows half of BenchLog: speech-to-text, sound identification and the code sandbox.
It implements [`docs/win-service-contract.md`](../../../docs/win-service-contract.md) and runs
on the Windows laptop (i9-12900H, RTX 3060 Laptop GPU 6 GB, 16 GB RAM).

| Endpoint | Does | Model / mechanism | Runs on |
|---|---|---|---|
| `POST /transcribe` | Speech to text with timestamps | Whisper large-v3-turbo, faster-whisper | GPU (float16), CPU int8 fallback |
| `POST /classify_sound` | Top sound labels | AST AudioSet classifier, 527 classes | CPU |
| `POST /run_code` | Runs generated analysis code | Separate venv, temp dir, 20 s timeout, no network | CPU |
| `GET /health` | `{"ok": true}` plus what is loaded | - | - |

Why these choices: turbo gives near large-v3 accuracy at about 1.6 GB, so it leaves most of
the 6 GB card to Ollama. The sound classifier is small enough for the CPU, which keeps it off
the GPU entirely. Uploads are decoded in memory and never written to disk.

## Setup (once, online)

1. Free about 7 GB on C:.
2. Double-click `setup.bat`. It builds `.venv` (service) and `sandbox_venv` (code sandbox)
   and downloads both models into `models/`.
3. Right-click `open_firewall.bat`, **Run as administrator**. Opens 8001 and 11434 to the
   local subnet only.

## Run

Double-click `run.bat` (or, from the repo root,
`uvicorn backend.services.win.app:app --host 0.0.0.0 --port 8001`). `stop.bat` stops it.
`run.bat` forces the model libraries offline, so the node makes no internet calls.

Then check it, which also writes `test_results.md`:

```
.venv\Scripts\python.exe check_node.py
```

**To let the M5 use `/run_code`**, edit `run.bat` and set `RUN_CODE_CLIENTS` to the M5's IP.
Until then `/run_code` answers this laptop only and the M5 gets HTTP 403, which makes the
orchestrator fall back to its local sandbox. See "Known limits" for why.

## Ollama (coder model)

The contract also has this laptop serve `qwen2.5-coder:7b` on port 11434:

```
ollama pull qwen2.5-coder:7b      (about 4.7 GB)
start_ollama.bat                  (quit the Ollama tray app first)
```

Whisper holds about 2.3 GB of the 6 GB card, and the 7B coder wants about 5 GB, so Ollama
will run part of the coder on the CPU while both are loaded. If that is too slow, set
`WHISPER_DEVICE=cpu` in `run.bat` or use a smaller coder.

## Responses

Contract keys are always present; the extra keys are additive.

```json
POST /transcribe (multipart "file"; optional form fields: language, task, domain, prompt)
{"text": "I added the lysis buffer...", "language": "en",
 "segments": [{"start": 0.0, "end": 4.2, "text": "..."}],
 "language_probability": 0.99, "duration": 10.4, "node": "WIN", "device": "cuda", "seconds": 0.9}

POST /classify_sound (multipart "file"; optional form field: top_k, default 3)
{"labels": [{"label": "Beep, bleep", "score": 0.71}, ...],
 "lab_events": [{"event": "alarm_or_timer", "score": 0.71, "evidence": ["Beep, bleep"],
                 "first_seen_s": 5.0, "description": "Instrument alarm, timer or beeper"}],
 "duration": 12.0, "node": "WIN", "device": "cpu", "seconds": 1.0}

POST /run_code (json {"code": str, "files": {name: base64}})
{"stdout": "slope=0.193\n", "stderr": "", "exit_code": 0,
 "artifacts": {"standard_curve.png": "<base64>"}, "node": "WIN", "seconds": 0.9}
```

- Any audio or video container works (wav, m4a, webm, mp4...), not only 16 kHz WAV.
- `domain=lab` gives Whisper a short list of bench vocabulary. Off by default.
- `lab_events` maps AudioSet labels to `alarm_or_timer`, `glass_break`, `liquid_handling`,
  `equipment_running`, `door_or_impact` and `speech`.
- Sound scores are the best 10-second window of the clip (5-second step).
- On timeout: `exit_code` is -1 and `stderr` ends with `Timed out after 20 s`.
- `artifacts` holds every `*.png` the script saved in its working directory.
- The sandbox has numpy, pandas, matplotlib and scipy (`requirements-sandbox.txt`).

## Known limits

- **The code sandbox is not a security boundary.** It gives each run a separate venv, a
  throwaway working directory, a clean environment, a timeout and a Python-level network
  block (`sandbox_guard.py`). Code can still read files on this laptop, and code that
  deliberately bypasses Python's socket module can reach the network. That is why
  `/run_code` only answers the IPs in `RUN_CODE_CLIENTS`. Run it on our own router, not
  venue Wi-Fi.
- **Lab events are a keyword mapping, not a lab-trained model.** AudioSet has no
  "centrifuge" or "freezer alarm" class; a beeping timer and a beeping freezer look the same.
- **`task=translate` is weak on the turbo model.** Use `WHISPER_MODEL=large-v3` (about 3 GB)
  if translation matters.
- **One request at a time per model**, and one sandbox run at a time. Others queue.
- Clips are capped at 15 minutes and 200 MB.
- If the GPU libraries fail to load, Whisper falls back to CPU int8. `/health` shows the
  device in use and the reason for any fallback.

## Settings

Model names and the sandbox timeout come from `backend/config.yaml` (`models.sound`,
`sandbox.timeout_s`, and optional `models.whisper_win`). Environment variables override:

| Variable | Default | Meaning |
|---|---|---|
| `RUN_CODE_CLIENTS` | `127.0.0.1,::1` | IPs allowed to call `/run_code`; `*` for any |
| `WHISPER_MODEL` | `large-v3-turbo` | Any faster-whisper model name |
| `WHISPER_DEVICE` | `auto` | `cuda` or `cpu` to force one |
| `MAX_AUDIO_SECONDS` | `900` | Longest clip accepted |
