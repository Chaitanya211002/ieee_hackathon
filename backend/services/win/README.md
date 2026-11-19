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

`run.bat` sets `RUN_CODE_CLIENTS=lan`: `/run_code` answers devices on the same local network
(private addresses on the same /24 as this laptop) and nobody else. See "Known limits".

## Moving to another network (demo day)

Nothing on this laptop is tied to an IP address, so nothing here needs editing:

- The service listens on every interface.
- The firewall rules (`open_firewall.bat`, once) allow the local subnet of whatever network
  the laptop is on.
- `RUN_CODE_CLIENTS=lan` follows the network too.

After joining the new network, run `net_info.bat`. It prints this laptop's name and address
there, checks the service and the firewall, and prints the value the M5 needs for
`nodes.win.service` (the M5 keeps it in a local copy of the config; see "Connecting the two" in
`CLAUDE.md`). Two forms it can take:

1. **By address**: always works. It changes with the network, so do this at the venue
   (unless the router gives this laptop a fixed IP). `net_info.bat` prints the current one.
2. **By name** (`http://laptop-8k7cobtd.local:8001`): set once, no edit at the venue, but it
   only works where mDNS passes between devices (own router, most phone hotspots) and has not
   been tested from the Mac yet. Check with `ping laptop-8k7cobtd.local` there, and that the
   reply comes from this laptop's Wi-Fi address (it also has VM and VPN adapters).

Do the online work before leaving: `setup.bat` needs the internet, the demo does not. Use our own router or a phone hotspot; venue Wi-Fi usually blocks laptop-to-laptop
traffic.

## Ollama (coder model): optional

The original plan had this laptop also serve `qwen2.5-coder:7b` on port 11434. It can, but it
should not while it is doing audio:

**The 6 GB card cannot hold Whisper and the 7B coder at once.** Measured on this laptop with
the orchestrator's settings (`num_ctx` 16384, about 245 output tokens):

| What is on the GPU | Coder speed | Coder on GPU | A 245-token answer | Whisper, 10 s clip |
|---|---|---|---|---|
| Whisper + coder | 12.5 tok/s | 48% (rest on CPU) | 20 s (first call: +50 s to load) | 0.7 s |
| Coder only, Whisper on CPU | 26.3 tok/s | 85% | 10 s (first call: +6 s) | 19 s |

So pick one job for this GPU. Whisper on the CPU is slower than real time, which rules out the
second row for audio. The split is Whisper and the sandbox here, the coder on the M5
(`routing.coder: m5` in `backend/config.yaml`). The service does not need Ollama at all.

Start `run.bat` before anything else uses the GPU. If a model is already filling it when the
service starts, Whisper silently falls back to the CPU; `/health` and `net_info.bat` show which
device it is on.

If the coder is ever routed here anyway: `ollama pull qwen2.5-coder:7b` (once, online, about
4.7 GB), then `start_ollama.bat`, which stops the tray app's Ollama and serves on 0.0.0.0. The
tray app itself only listens on this laptop unless the user environment variable
`OLLAMA_HOST=0.0.0.0` is set.

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
  `/run_code` only answers `RUN_CODE_CLIENTS`. With `lan`, that is every device on the same
  local network, so run it on our own router or hotspot, never on venue Wi-Fi. To lock it to
  the M5 alone, put the M5's IP there instead.
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
| `RUN_CODE_CLIENTS` | `127.0.0.1,::1` (`run.bat` sets `lan`) | Who may call `/run_code`: IPs, `lan` (same local network), or `*` |
| `WHISPER_MODEL` | `large-v3-turbo` | Any faster-whisper model name |
| `WHISPER_DEVICE` | `auto` | `cuda` or `cpu` to force one |
| `MAX_AUDIO_SECONDS` | `900` | Longest clip accepted |
