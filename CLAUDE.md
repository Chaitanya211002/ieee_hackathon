# CLAUDE.md — BenchLog

Offline multimodal lab notebook for wet-lab researchers. Built for the IEEE AI Hackathon
(Multimodal LLM Challenge), Roux Institute, Nov 18–20, 2026.

## The product in one paragraph

A grad student at the bench captures photos (plates, gels), voice notes, short video clips,
protocol questions, and analysis requests. Each capture becomes a timestamped, hash-chained
notebook entry that a local AI annotates. At the end of the day they export a clean lab log.
Everything runs on laptops the lab already owns. Nothing leaves the local network.

## Hard rules (hackathon constraints — never break these)

- **Open-weight models only, running locally.** Never add OpenAI, Anthropic, Gemini, or any
  cloud inference API to the runtime, even as a fallback. No network calls outside the LAN.
- AI coding tools may write code; they must never be part of the running system.
- The demo must show all five modalities working in one interface:
  image, audio (speech + sound ID), text (with refusal), code, video.
- The app must keep working when any single non-M5 node is unplugged (fallback to M5).

## Architecture

```
React PWA (laptop + phone over LAN)
        │
FastAPI orchestrator (M5) ── routes by file type, NOT by LLM
        ├── vision    → Qwen3-VL 8B (images, video frames, doc Q&A)
        ├── audio     → Whisper large-v3-turbo + AST sound classifier
        ├── coder     → Qwen2.5-Coder 7B + sandboxed execution
        └── docs      → nomic-embed-text + Chroma, grounded answers
        │
SQLite notebook (hash-chained entries) + local media folder
```

### Node assignment

| Node | Hardware | Runs |
|---|---|---|
| M5 (primary, this machine) | MacBook Air M5, 24 GB | Orchestrator, frontend, Qwen3-VL 8B (images, video, doc Q&A), nomic-embed-text, Chroma, SQLite. Also the local fallback for EVERY job. |
| WIN (teammate's laptop) | i9-12th gen, RTX 3060 6 GB, 16 GB RAM | Qwen2.5-Coder 7B on GPU via Ollama, audio service (Whisper CUDA + AST), code sandbox. Built by a teammate; the M5 side has the client + local fallbacks. Contract: `docs/win-service-contract.md`. |

There is no M1 node anymore (two laptops only).

Node URLs live in `backend/config.yaml`. The orchestrator health-checks every node every
5 s; if a node is down, its job reroutes to the M5. The full stack fits on the M5 alone
(~13 GB), so single-machine mode must always work. **Build and test on the M5 first;
distribute last.**

## Repo layout

```
backend/
  main.py          # FastAPI app, POST /entry, GET /entries, GET /export
  router.py        # file-type routing + node fallback
  config.yaml      # node URLs, model names, thresholds
  pipelines/       # vision.py, audio.py, video.py, docs.py, code.py
  sandbox/         # code execution (subprocess, timeout, no network)
  store.py         # SQLite + hash chain + Chroma
  services/win/    # FastAPI service that runs on the Windows node
frontend/          # React + Vite + Tailwind PWA
eval/
  run_eval.py      # runs the Kaggle practice pack through the real pipelines
  results.md       # per-modality metrics table (goes on a slide)
data/              # local only, gitignored: media, sqlite db, chroma
```

## Commands

```bash
# M5
OLLAMA_HOST=0.0.0.0 OLLAMA_KEEP_ALIVE=-1 OLLAMA_MAX_LOADED_MODELS=3 ollama serve
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
cd frontend && npm run dev -- --host

# Windows node
uvicorn backend.services.win.app:app --host 0.0.0.0 --port 8001

# (no M1 node: Qwen2.5-Coder runs on WIN via Ollama, OLLAMA_HOST=0.0.0.0)

# Eval
python eval/run_eval.py --pack data/practice-pack --out eval/results.md
```

## API contract (frozen — frontend depends on it)

`POST /entry` (multipart: optional `file`, optional `text`, `experiment_id`) returns:

```json
{
  "id": "uuid",
  "type": "voice | photo | video | protocol_qa | analysis | note",
  "created_at": "ISO-8601",
  "summary": "one-line human summary",
  "details": {},
  "artifacts": [{"kind": "image|plot|code|transcript", "path": "..."}],
  "hash": "sha256 hex",
  "prev_hash": "sha256 hex",
  "node": "M5 | WIN | M1"
}
```

Do not change this shape without updating `frontend/src/types.ts` in the same change.
Add new fields inside `details`; never rename top-level keys.

## Pipeline requirements

- **Image:** describe the image, answer follow-ups. For colony counts, run the OpenCV
  blob count alongside the VLM and return both. Never present a VLM count alone as exact.
- **Audio:** Whisper transcript plus top-3 AST labels with confidence. Only surface sound
  events with confidence ≥ 0.5 in the summary.
- **Video:** ffmpeg at 1 fps, max 8–12 frames, long side ≤ 768 px. Frames go to Qwen3-VL as
  one ordered sequence; the audio track goes through the audio pipeline. Merge both into one entry.
- **Docs:** chunks of ~500 words with section titles kept. Retrieve the top 4. The prompt must
  require answers only from the excerpts, with a section citation. If the best similarity is
  below the threshold in `config.yaml`, or the model returns `NOT_IN_PROTOCOLS`, show
  "Not in your indexed protocols." Correct refusal is a scored checklist item; never weaken it.
- **Code:** generate Python, run it in the sandbox (separate venv, 20 s timeout, no network,
  temp working dir). On error, feed the traceback back for up to 2 retries. Return the code,
  stdout, and any saved plot. Never show code that hasn't been executed as "working."
- **Hash chain:** `hash = sha256(prev_hash + canonical_json(entry_without_hash))`.
  `GET /verify` recomputes the chain and reports the first broken entry, if any.

## Conventions

- Python 3.11, type hints, `ruff` formatting. Keep pipelines as pure functions:
  input path/text in, dict out. Pipelines must not touch the DB directly.
- All model names, URLs, and thresholds go in `config.yaml`, never hardcoded.
- Every pipeline call logs latency and which node served it (needed for the eval and slides).
- Frontend: functional components, Tailwind, one card component per entry type. The UI must
  work at phone width (~390 px).
- Commit small and often, with clear messages. Push to the IEEE GitHub repo frequently;
  the code deadline is hard.
- Commit messages: plain descriptive messages only. Never add Co-Authored-By trailers,
  "Generated with Claude Code" lines, or session links.

## Known gotchas

- faster-whisper does not use the Mac GPU. On Macs use `mlx-whisper`; on Windows use
  faster-whisper with CUDA (falls back to CPU int8 if CUDA setup fails).
- The MacBook Air is fanless and throttles under sustained load. Keep video frames small.
- Windows firewall must allow ports 8001 and 11434 for the LAN.
- Don't use venue Wi-Fi (client isolation). Use our own router, switch, or a phone hotspot,
  with fixed IPs.
- VLMs are unreliable at counting; that's why the OpenCV count exists.

## Priorities when time is short

1. All five modalities working end to end on the M5 alone.
2. Basic working UI, including on a phone.
3. `eval/results.md` from the practice pack.
4. README with hardware, model choices and reasons, setup, and known limits.
5. Distribution across nodes with fallback.
6. Polish, export formats, extra features.

Never break a working demo path to add a feature. If unsure, add it behind a config flag.

## When working in this repo, Claude should

- Read this file and `config.yaml` before making changes.
- Prefer small, testable changes. Run the relevant pipeline script on a sample from
  `data/practice-pack` after changing it.
- Ask before adding a new dependency, changing the API contract, or touching the hash chain.
- Flag anything that would require internet access at runtime.
