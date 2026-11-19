# CLAUDE.md — BenchLog

Offline multimodal lab notebook for wet-lab researchers. Built for the IEEE AI Hackathon
(Multimodal LLM Challenge), Roux Institute, Nov 18–20, 2026.

This file is shared by every laptop on the team (it is in git). Write it for all of them:
no "this machine", and when you change something that affects the other laptop (an endpoint,
a config key, a port, a model), update this file in the same commit.

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
- Never commit the practice pack or anything from it (files or answers): its license forbids
  it. `data/`, `*.zip` and `eval/raw/` are gitignored; keep it that way.

## Architecture

```
React PWA (laptop + phone over LAN)
        │
FastAPI orchestrator (M5) ── routes by file type, NOT by LLM
        ├── vision    → Qwen3-VL 8B Instruct (images, video frames, doc Q&A)
        ├── audio     → Whisper large-v3-turbo + AST sound classifier
        ├── coder     → Qwen2.5-Coder 7B + sandboxed execution
        └── docs      → nomic-embed-text + Chroma, grounded answers
        │
SQLite notebook (hash-chained entries) + local media folder
```

### Nodes (two laptops; there is no M1 node)

| Node | Hardware | Runs | Owns (edits) |
|---|---|---|---|
| **M5** (primary) | MacBook Air M5, 24 GB, macOS, fanless | Orchestrator, frontend, Qwen3-VL 8B Instruct, nomic-embed-text, Chroma, SQLite. Also the local fallback for EVERY job. | everything outside `backend/services/win/` |
| **WIN** | i9-12900H, RTX 3060 6 GB, 16 GB RAM, Windows | Qwen2.5-Coder 7B on the GPU (Ollama), WIN service on :8001 (Whisper on CUDA + AST + code sandbox) | `backend/services/win/` |

**Which laptop am I on?** macOS → M5. Windows → WIN. Work in the area that laptop owns.
Changing the other node's code, or the WIN service contract (`docs/win-service-contract.md`),
needs both sides: say so to the user instead of silently editing across the boundary.

Node URLs live in `backend/config.yaml` (`nodes.win` holds `WIN_IP` until the Windows laptop's
name or IP is filled in; while it is the placeholder, every job runs on the M5, and the M5
tests and eval rely on that). The orchestrator
health-checks every node every 5 s; if a node is down, or a call to it fails or times out, the
job reruns on the M5. The full stack fits on the M5 alone (~16 GB with every model loaded), so
single-machine mode must always work. **Build and test on the M5 first; distribute last.**

## Repo layout

```
backend/
  main.py          # FastAPI app: /entry, /entries, /verify, /status, /export, /protocols, /experiments, /media
  router.py        # file-type routing (which pipeline, which entry type)
  nodes.py         # node health checks + run_job(): try the routed node, fall back to the M5
  config.py        # loads config.yaml; forces HF/transformers/Chroma offline
  config.yaml      # node URLs, model names, thresholds (shared by both laptops)
  pipelines/       # vision.py, audio.py, video.py, docs.py, code.py (pure functions)
  sandbox/         # local.py: M5 fallback executor; guard.py: socket block for the sandbox venv
  store.py         # SQLite + hash chain
  services/win/    # WIN node: FastAPI service, setup/run .bat files, check_node.py
docs/              # win-service-contract.md (the M5 <-> WIN contract)
frontend/          # React + Vite + Tailwind PWA (src/types.ts mirrors the API contract)
scripts/           # run_<pipeline>.py: one pipeline on one file; setup_sandbox.sh; prefetch_models.py
tests/             # pytest (M5); model tests skip when Ollama or the practice pack is missing
eval/
  run_eval.py      # runs the practice pack through the real pipelines
  results.md       # per-modality metrics table (goes on a slide)
data/              # local only, gitignored: practice pack, media, sqlite db, chroma, sandbox venv
```

Two separate Python environments, never shared: the M5 uses `.venv` (`requirements.lock.txt`,
transformers 5.x, mlx-whisper); the WIN service uses `backend/services/win/.venv`
(`requirements-win.txt`, faster-whisper, transformers < 5, CUDA wheels).

## Commands

### M5 (macOS)

```bash
# one-time setup (online)
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.lock.txt
ollama pull qwen3-vl:8b-instruct && ollama pull qwen2.5-coder:7b && ollama pull nomic-embed-text
.venv/bin/python scripts/prefetch_models.py     # mlx Whisper + AST into the HF cache
./scripts/setup_sandbox.sh                      # data/sandbox_venv for the local code sandbox
cd frontend && npm install && cd ..

# run (three terminals)
OLLAMA_HOST=0.0.0.0 OLLAMA_KEEP_ALIVE=-1 OLLAMA_MAX_LOADED_MODELS=3 ollama serve
.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev -- --host            # phone: http://<M5-IP>:5173

# test
.venv/bin/python -m pytest                      # whole suite (~4 min with models)
.venv/bin/python scripts/run_vision.py data/practice-pack/image/p_img_002.jpg "How many people?"
.venv/bin/python eval/run_eval.py --pack data/practice-pack --out eval/results.md   # ~30 min
```

### WIN (Windows, from `backend\services\win`)

```bat
setup.bat            :: one-time (online): .venv, sandbox_venv, model downloads
open_firewall.bat    :: once, as administrator: allow TCP 8001 and 11434 from the local subnet
start_ollama.bat     :: Ollama on 0.0.0.0:11434 serving qwen2.5-coder:7b
run.bat              :: WIN service on :8001 (sets RUN_CODE_CLIENTS=lan)
net_info.bat         :: this laptop's name/IP on the current network, checks, the nodes.win line
.venv\Scripts\python.exe check_node.py   :: smoke test; writes test_results.md
```

`/run_code` only answers clients allowed by `RUN_CODE_CLIENTS`: IPs, `lan` (private addresses
on the same /24 as the WIN laptop; what `run.bat` sets) or `*`. A client that is not allowed
gets 403 and its code jobs silently fall back to the M5.

### Connecting the two (and moving to another network)

Own router or phone hotspot, never venue Wi-Fi. Nothing on the WIN laptop is tied to an IP, so
it needs no edits on a new network; run `net_info.bat` there to check it. On the M5, replace
`WIN_IP` in `backend/config.yaml` (`nodes.win.ollama` and `nodes.win.service`) with either:

- the address `net_info.bat` prints: always works, but changes with the network (so redo this
  step at the demo venue); or
- the WIN laptop's mDNS name, `laptop-8k7cobtd.local`: the same on every network, but only
  where mDNS passes between devices. Not yet tested from the Mac; check with
  `ping laptop-8k7cobtd.local` and that it answers from the WIN laptop's Wi-Fi address.

Restart the orchestrator, then check `GET http://<M5-IP>:8000/status`: every WIN job should
show `"serving": "WIN"`. Keep that edit local (don't commit it): the M5 tests and eval expect
the placeholder. A name that does not resolve costs a few seconds per health probe, so if the
WIN laptop is not on the network, put `WIN_IP` back.

## API contract (frozen — frontend depends on it)

`POST /entry` (multipart: optional `file`, optional `text`, optional `question`,
`experiment_id`, optional `follow_up_of`) returns:

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
Add new fields inside `details`; never rename top-level keys. Artifact `path`s are
`/media/...` URLs. The original upload is in `details.media`. Every route is also served
under `/api/...` for the frontend.

Routing (`backend/router.py`): image → `photo`, audio → `voice`, video → `video` (a video file
with no video stream → `voice`), PDF/TXT/MD → index it, and answer `text` as a question →
`protocol_qa` (no question → `note`), CSV/TSV + request → `analysis`, text starting with
`code:` or a code request → `analysis`, other questions → `protocol_qa`, anything else → `note`.

The M5 ↔ WIN contract is in `docs/win-service-contract.md`; extra response keys are allowed,
renaming or removing keys is not.

## Pipeline requirements

- **Image:** describe the image, answer follow-ups (`follow_up_of` = a photo or video entry id;
  the stored media plus the thread's earlier Q&A go back to the VLM; the new entry records
  `follow_up_of`, `thread_root` and `history` in `details`). For colony counts, run the OpenCV
  blob count alongside the VLM and return both. Never present a VLM count alone as exact.
- **Audio:** Whisper transcript plus top-3 AST labels with confidence (sigmoid scores on both
  nodes). Only surface sound events with confidence ≥ 0.5 in the summary.
- **Video:** at most `video.max_frames` (10) frames, evenly spaced from the first to the last
  frame, long side ≤ 768 px. Frames go to Qwen3-VL in order in one message: by default as
  timestamped contact sheets (`video.mode: sheets`, ~35 s per clip on the M5), or one image per
  frame (`video.mode: frames`, ~2 min). The audio track goes through the audio pipeline. Merge
  both into one entry.
- **Docs:** chunks of ~500 words with section titles kept. Retrieve the top 4. The prompt must
  require answers only from the excerpts, with a section citation. If the best similarity is
  below the threshold in `config.yaml`, or the model returns `NOT_IN_PROTOCOLS`, or a number
  in the question or answer is not in the retrieved excerpts, show
  "Not in your indexed protocols." Correct refusal is a scored checklist item; never weaken it.
- **Code:** generate Python, run it in the sandbox (separate venv, 20 s timeout, no network,
  temp working dir). On error, feed the traceback back for up to 2 retries. Return the code,
  stdout, and any saved plot. Never show code that hasn't been executed as "working."
- **Hash chain:** `hash = sha256(prev_hash + canonical_json(entry_without_hash))`.
  `GET /verify` recomputes the chain and reports the first broken entry, if any.

## Conventions

- Python 3.11, type hints, `ruff` formatting (line length 120). Keep pipelines as pure
  functions: input path/text in, dict out. Pipelines must not touch the DB directly.
- All model names, URLs, and thresholds go in `config.yaml`, never hardcoded.
- Every pipeline call logs latency and which node served it (needed for the eval and slides).
- Frontend: functional components, Tailwind, one card component per entry type. The UI must
  work at phone width (~390 px).
- Git: `git pull` before starting. Work on a branch (one per laptop or feature) and merge to
  `main` through a pull request. Commit small and often, with clear messages, and push
  frequently; the code deadline is hard.
- Commit messages: plain descriptive messages only. Never add Co-Authored-By trailers,
  "Generated with Claude Code" lines, or session links.
- `backend/services/win/test_results.md` holds the real Windows/GPU results. Running
  `check_node.py` anywhere else overwrites it; don't commit those runs.

## Known gotchas

- faster-whisper does not use the Mac GPU. On Macs use `mlx-whisper`; on Windows use
  faster-whisper with CUDA (falls back to CPU int8 if CUDA setup fails).
- The NVIDIA wheels in `requirements-win.txt` don't exist for macOS. To run the WIN service on a
  Mac for testing, install that file without the `nvidia-*` lines (Whisper then runs on CPU).
  `check_node.py`'s speech tests need Windows text-to-speech and are skipped elsewhere.
- The MacBook Air is fanless and throttles under sustained load (long evals, back-to-back videos).
- Windows firewall must allow ports 8001 and 11434 for the LAN.
- The RTX 3060's 6 GB cannot hold Whisper and Qwen2.5-Coder 7B together at `num_ctx` 16384.
  Measured on WIN: with both loaded the coder runs 48% on the GPU at 12.5 tok/s (50 s cold
  load); alone it reaches 26 tok/s, but Whisper on the CPU then takes 19 s for a 10 s clip.
  Compare `routing.coder: win` against `m5` before the demo; details in the WIN README.
- Don't use venue Wi-Fi (client isolation). Use our own router, switch, or a phone hotspot,
  with fixed IPs.
- VLMs are unreliable at counting; that's why the OpenCV count exists.
- Use `qwen3-vl:8b-instruct`, not `qwen3-vl:8b`: the plain tag is the thinking variant and
  ignores `think=false` (2-3x slower).
- Ollama resizes every image to ~1k tokens (~10 s prefill each on the M5) regardless of input
  size, so shrinking frames does not speed up video; fewer images does (`video.mode: sheets`).
- Ollama reloads a model whenever `num_ctx` changes. Keep one `llm.num_ctx` for every call.
- Browsers only allow in-page microphone recording on https or localhost. On a phone over
  `http://<M5-IP>` the voice button opens the system recorder instead.

## Priorities when time is short

1. All five modalities working end to end on the M5 alone.
2. Basic working UI, including on a phone.
3. `eval/results.md` from the practice pack.
4. README with hardware, model choices and reasons, setup, and known limits.
5. Distribution across nodes with fallback.
6. Polish, export formats, extra features.

Never break a working demo path to add a feature. If unsure, add it behind a config flag.

## When working in this repo, Claude should

- Read this file and `config.yaml` before making changes, and work out which laptop it is on.
- Prefer small, testable changes. Run the relevant pipeline script on a sample from
  `data/practice-pack` after changing it (M5), or `check_node.py` (WIN).
- Ask before adding a new dependency, changing the API contract or the WIN service contract,
  or touching the hash chain.
- Flag anything that would require internet access at runtime.
