# BenchLog

An offline AI lab notebook for wet-lab researchers. At the bench you capture plate photos,
voice notes, short video clips, protocol questions and analysis requests; each capture becomes
a timestamped, hash-chained notebook entry that a local open-weight model annotates. At the
end of the day you export a clean Markdown lab log. Everything runs on two laptops the lab
already owns, and nothing leaves the local network.

Built for the IEEE AI Hackathon (Multimodal LLM Challenge), Roux Institute, November 18–20, 2026.

## What it does

| You capture | BenchLog does | Entry |
|---|---|---|
| Photo (plate, gel, label, anything) | Qwen3-VL describes it or answers your question. For colony questions it also runs an OpenCV blob count and shows both numbers; the VLM number is always labelled an estimate. For a reading, a label or other small detail it first looks closer: the model marks where the answer is, that part is cut from the full-resolution photo, and both images go into the answer (the card shows the crop). Follow-up questions are asked in the photo's own card and stay there as one thread, with the earlier answers as context. | `photo` |
| Voice note or sound | Whisper transcript plus the top-3 AudioSet sound labels (AST). Sounds with confidence ≥ 0.5 show as alerts. Questions are answered from the transcript and labels. | `voice` |
| Video clip | Up to 10 frames, evenly spaced from the first to the last frame, sent to Qwen3-VL in order as one sequence; the audio track (if any) goes through the audio pipeline. Follow-up questions reuse the stored frames and stay in the clip's card. | `video` |
| Protocol PDF / text + a question | Answers only from your indexed protocols, with a section citation, or says **"Not in your indexed protocols."** | `protocol_qa` |
| `code: …`, a CSV + a request, or "Complete this Python function…" | Qwen2.5-Coder writes Python, the sandbox runs it, errors are fed back (up to 2 retries). Code, stdout and plots are shown, and only code that actually ran is marked "Executed". | `analysis` |
| Any other text | Saved as a log note. | `note` |

Every entry is chained: `hash = sha256(prev_hash + canonical_json(entry_without_hash))`.
`GET /verify` recomputes the chain and names the first entry that was edited or deleted.

## Hardware

| Node | Machine | Runs |
|---|---|---|
| **M5** (primary) | MacBook Air M5, 24 GB unified memory, fanless | FastAPI orchestrator, React frontend, Qwen3-VL 8B (images, video, doc Q&A), Qwen2.5-Coder 7B, nomic-embed-text, Chroma, SQLite. Also the local fallback for **every** job. |
| **WIN** | Windows laptop, i9-12900H, RTX 3060 6 GB, 16 GB RAM | Whisper large-v3-turbo on CUDA + AST sound classifier, code sandbox (`backend/services/win/`). |

The whole stack fits on the M5 alone (about 16 GB with every model loaded, including the coder fallback), so the demo works
with the Windows laptop unplugged.

## Models and why

| Job | Model | Why this one |
|---|---|---|
| Images, video, doc answers | **Qwen3-VL 8B Instruct** (`qwen3-vl:8b-instruct`, Ollama) | Strongest open-weight VLM that fits next to everything else in 24 GB; reads text in photos well and handles multi-image input for video. We use the *instruct* build: the plain `qwen3-vl:8b` tag is the thinking variant, which ignores `think=false` and was 2–3× slower (and miscounted more) in our tests. One model also serves text Q&A, so no second LLM sits in memory. |
| Code | **Qwen2.5-Coder 7B** (Ollama, on the M5) | Best open coding model at this size. It runs on the M5: the RTX 3060's 6 GB cannot hold it (6.5 GB at a 16k context) next to Whisper, and with both loaded it dropped to 12.5 tok/s, half on the CPU. The generated code still runs in the WIN sandbox when WIN is connected. |
| Speech | **Whisper large-v3-turbo** | Near large-v3 accuracy at a fraction of the decode cost. faster-whisper on CUDA on WIN; **mlx-whisper** on the M5 (faster-whisper cannot use the Mac GPU). |
| Sound events | **AST** fine-tuned on AudioSet (`MIT/ast-finetuned-audioset-10-10-0.4593`) | 527 everyday sound classes (alarms, beeps, glass, liquid, speech); small enough for CPU. Scored with sigmoid, since AudioSet is multi-label. |
| Retrieval | **nomic-embed-text** + Chroma | Small, fast, good retrieval quality; uses the `search_document:` / `search_query:` prefixes it was trained with. |
| Colony counts | **OpenCV** (adaptive threshold + contour area/circularity) | VLMs are unreliable counters; a deterministic count is shown next to the VLM estimate. |

No cloud API is used anywhere, not even as a fallback. Hugging Face and Chroma telemetry are
forced offline at import (`backend/config.py`).

## Setup

You need internet once, to install packages and download models. After that, everything runs
with Wi-Fi off.

### M5 (macOS)

```bash
# Python 3.11 environment
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.lock.txt

# Models (once, while online)
ollama pull qwen3-vl:8b-instruct
ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text
.venv/bin/python scripts/prefetch_models.py   # mlx Whisper + AST into the HF cache

# Code sandbox: a separate venv with numpy/pandas/matplotlib and a network guard
./scripts/setup_sandbox.sh

# Frontend
cd frontend && npm install && cd ..
```

Run it:

```bash
./scripts/start_m5.sh          # starts Ollama, the orchestrator and the frontend
./scripts/start_m5.sh --stop   # stops the orchestrator and frontend
```

It checks whether the Windows laptop is reachable and picks the mode by itself: **two laptops**
when it answers (audio and the code sandbox go to WIN), otherwise **single laptop** (every job on
the Mac). So the same command works at home with both laptops and at a venue with only the Mac.
`--solo` forces single-laptop mode. The equivalent by hand, in three terminals:

```bash
OLLAMA_HOST=0.0.0.0 OLLAMA_KEEP_ALIVE=-1 OLLAMA_MAX_LOADED_MODELS=3 ollama serve
BENCHLOG_CONFIG=$(.venv/bin/python scripts/pick_config.py) .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev -- --host
```

Open `http://localhost:5173` on the laptop, or `http://<M5-IP>:5173` on a phone on the same
network. (Alternatively, `npm run build` and the API serves the built app at `http://<M5-IP>:8000`.)

### WIN (Windows)

See `backend/services/win/README.md`. In short: run `setup.bat` once while online, open the
service port in the Windows firewall (`open_firewall.bat`, once, as administrator), then
`run.bat`. The sandbox accepts requests from devices on the same local network
(`RUN_CODE_CLIENTS=lan`).

### Demo with only the Mac

If the Windows laptop stays behind (for example at home while the Mac goes to the venue), just
run `./scripts/start_m5.sh` at the venue. It finds no Windows laptop and runs everything on the
Mac; the status panel shows the Windows node offline and its jobs as "M5 (fallback)". The eval
numbers below were measured in this mode. The Mac does not connect back to the home network:
that would need the internet, which the app never uses.

With Wi-Fi off, open the app on the Mac itself (`http://localhost:5173`). To also use a phone,
both need a local network: a phone hotspot with mobile data switched off works.

### Connect the two

Put both laptops on your own router or a phone hotspot (venue Wi-Fi usually blocks
laptop-to-laptop traffic). The Windows laptop needs no changes on a new network: run
`net_info.bat` there and it prints its current address. `./scripts/start_m5.sh` usually finds
it by itself (by the laptop's mDNS name). If it can't, put that address in a local copy of the config (the tracked `backend/config.yaml` keeps the `WIN_IP` placeholder, which the
tests and eval rely on) and start the orchestrator with it:

```bash
cp backend/config.yaml data/config.local.yaml     # data/ is gitignored
# edit data/config.local.yaml:   nodes.win.service: http://192.168.8.20:8001
BENCHLOG_CONFIG=data/config.local.yaml .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Re-copy the file whenever `backend/config.yaml` changes.

The address changes with the network, so repeat this at a new venue. The Windows laptop's
mDNS name (`laptop-8k7cobtd.local`) can be used in place of the address where the network
passes mDNS; check with `ping laptop-8k7cobtd.local` on the Mac first.

## How fallback works

`backend/config.yaml` `routing` says which node serves each job (`vision`, `docs`, `coder` → M5;
`audio`, `sandbox` → WIN). A background loop checks every node every 5 s (Ollama
`/api/tags`, WIN service `/health`). When a job's node is up, the request goes there; if it is
down, or the call errors or times out mid-request, the job runs on the M5 instead and is
marked as a fallback in the entry and in the status panel. A WIN failure never fails a
capture. While `WIN_IP` is left as the placeholder, everything runs on the M5.

## API

| Method | Path | |
|---|---|---|
| POST | `/entry` | multipart: `file?`, `text?`, `question?`, `experiment_id`, `follow_up_of?` → entry (contract in `CLAUDE.md`). `follow_up_of` = id of a photo/video entry to ask another question about. |
| GET | `/entries` | `?experiment_id=&date=YYYY-MM-DD` |
| GET | `/verify` | hash-chain check, first broken entry |
| GET | `/status` | node health, which node serves each job, models |
| GET | `/export` | `?date=&experiment_id=` → Markdown lab log with hashes |
| POST/GET | `/protocols` | upload a PDF/TXT to index / list indexed protocols |
| GET/POST | `/experiments` | list / create |
| GET | `/media/...` | captured files, frames, plots |

Every route is also available under `/api/...` (used by the frontend).

## Eval

`python eval/run_eval.py --pack data/practice-pack --out eval/results.md` runs all 100
practice-pack items through the real pipelines on the M5 alone. Full table:
[`eval/results.md`](eval/results.md).

Latest run (100 items, 24 min, single-machine mode: every job on the M5):

| Modality | Metric | Result |
|---|---|---|
| Image | Counting accuracy | 93% (14/15) |
| Image | Identification accuracy | 100% (10/10) |
| Audio | Word error rate, transcription | 2.1% |
| Audio | Speech Q&A accuracy | 80% (4/5) |
| Audio | Sound identification | 80% (8/10); correct sound in AST top-3: 90% |
| Text | Answerable questions correct | 93% (14/15) |
| Text | Unanswerable questions correctly refused | **100% (5/5)**, with 0 false refusals |
| Code | Hidden unit tests passed | 90% (18/20); all 20 generated programs ran |
| Video | Question accuracy | 67% (10/15) |

Mean latency on the M5: image 9.6 s, audio 5.4 s, text 7.0 s, code 22.9 s, video 34.6 s.
Scoring is automatic and deliberately strict: one of the audio misses ("His country home was in
Essex" for "An old family place in Essex") is a correct answer that the word-overlap check
rejects. Video misses are fine-motion and counting clips (bounces, shapes appearing and
disappearing).

## Tests

```bash
.venv/bin/python -m pytest            # 54 tests; model tests skip if Ollama or the pack is missing
```

Per-pipeline scripts for trying one file: `scripts/run_vision.py`, `run_audio.py`,
`run_video.py`, `run_docs.py`, `run_code.py` (each logs latency and the node that served it).

## Logs

`.venv/bin/python scripts/diagnose.py` summarises what the app has been doing: failed or rejected
captures with the end of the traceback, Windows-laptop up/down changes, fallbacks to the Mac,
errors the browser hit (including phones), and latency per entry type. The raw data is in
`data/logs/events.jsonl` (one JSON line per event), with full server logs in `data/logs/api.log`.

## Known limits

- **VLM counting.** Qwen3-VL miscounts crowded scenes (e.g. 3 zebras for 4). The UI always labels
  VLM counts as estimates; plates get the OpenCV count alongside. The OpenCV counter is tuned
  for separated round colonies; touching or confluent colonies are under-counted.
- **Fine readings in photos.** Photos are downscaled to 1024 px for the model, which hides small
  print. Questions about readings, labels and displays therefore get a second, enlarged crop
  (`vision.zoom`), which takes 14–18 s on the M5 instead of 3–9 s. On our own lab photos it
  fixed a burette reading (4.2 mL against a true 4.3; 6.5 before); faint or blurred markings
  can still be missed, and the answer depends on the model boxing the right spot.
- **Video speed.** Ollama resizes every image to a fixed ~1k tokens, and on the M5 the VLM
  prefills about 100 tokens/s, so each image costs about 10 s. Sending 10 frames separately took
  about 2 minutes, so frames are tiled in order into two labelled contact sheets
  (`video.mode: sheets`), about 35–40 s per clip. Set `video.mode: frames` for one image per frame.
  Fine motion (counting bounces) is the weakest video case.
- **Sandbox isolation.** Generated code runs in a separate venv, in a temp directory, with a
  20 s timeout, a minimal environment, a Python-level socket block, and on macOS `sandbox-exec`
  with all network denied. It is not a hardened jail: code can still read files the user can read.
  Fine for the lab's own analysis code; not a boundary against deliberately hostile code.
- **Air thermals.** The MacBook Air is fanless and throttles under sustained load (long eval runs,
  back-to-back videos). Keep the WIN node connected for audio and code to spread the load.
- **Phone voice notes.** Browsers only allow in-page recording on `https` or `localhost`. Over
  `http://<M5-IP>` the voice button opens the phone's own recorder instead (works on Android;
  on iOS, use the file button with a Voice Memos recording).
- **Doc refusals.** Besides the similarity threshold and the model's `NOT_IN_PROTOCOLS`, answers
  are refused when a number in the question or answer does not appear in the retrieved excerpts.
  That catches altered-detail questions (a wrong year or count) but not every unanswerable question.
