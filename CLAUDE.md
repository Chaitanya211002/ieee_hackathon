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

## Open handoff: WIN → M5 (delete this section once every item is done)

Written from the WIN laptop on Nov 19. **If you are on the M5 (macOS), items 1–4 are yours.**
The WIN side cannot do them: they change files the M5 owns, or have to run on the Mac. Work
through them in order without waiting for the WIN side; where a person is needed, it says so.
If you are on WIN, only item 5 concerns you.

**Where the WIN node stands.** The service runs and passes `check_node.py` 16/16 over its LAN
address. Whisper is on the GPU: 0.7 s for a 10 s clip, against 5.4 s mean per audio item on the
M5 in `eval/results.md`. Nothing on WIN is tied to an IP address, so it needs no edits on a new
network. Not done: nothing has been called from the Mac yet, and the Windows firewall rules are
still missing (item 5), so the M5 cannot reach WIN until a person adds them.

1. **[Done on the M5, Nov 19]** **Move the coder to the M5.** In `backend/config.yaml` set `routing.coder: m5`, and commit.
   Why: the RTX 3060 has 6 GB. Whisper holds 2.3 GB and Qwen2.5-Coder 7B needs 6.5 GB at
   `num_ctx` 16384 (4.7 GB of weights alone). Measured on WIN: with both loaded, Ollama keeps
   48% of the coder on the GPU and it runs at 12.5 tok/s after a 50 s cold load; alone it
   reaches 26.3 tok/s, but Whisper on the CPU then takes 19 s for a 10 s clip. Audio is the
   job that GPU is good at. Keep `audio: win` and `sandbox: win`. Nothing changes while WIN
   is unconfigured, so the tests and the eval numbers are unaffected.

2. **[Done on the M5, Nov 19]** **Make the docs say the same thing, in that commit.** The Nodes table and architecture
   notes in this file; the Hardware and "Models and why" tables in `README.md` (the coder row
   says it fits the 3060's 6 GB, which only holds with nothing else loaded); the WIN paragraph
   in `README.md` (no Ollama needed there); `docs/win-service-contract.md` (drop "plus Ollama
   on 11434 serving qwen2.5-coder:7b" and the Ollama and port-11434 notes); and the slides if
   they say where the coder runs. The WIN side agrees to that contract change, so you do not
   need to ask for it. The four endpoints do not change.

3. **[Done on the M5, Nov 19, home network: WIN at 192.168.0.113 via mDNS, `/health` ok, cuda, `["lan"]`]** **Find and check the WIN laptop** once both laptops are on the same network (own router or
   phone hotspot, not venue Wi-Fi). You can find its address yourself:

   ```bash
   dscacheutil -q host -a name laptop-8k7cobtd.local   # every address WIN answers with
   ipconfig getifaddr en0                               # this Mac's address
   ```

   Use the WIN address on the Mac's own subnet; WIN also has VM and VPN adapters, ignore
   those. If the name does not resolve, the network blocks mDNS: ask the user for the address
   that `net_info.bat` shows on the Windows laptop. Check it before changing anything:

   ```bash
   curl -s --max-time 3 http://<WIN-ADDR>:8001/health
   ```

   A good answer has `"ok": true`, `speech.device` `"cuda"` and `sandbox.allowed_clients`
   `["lan"]`. No answer means the firewall rules are missing (item 5) or the network blocks
   laptop-to-laptop traffic. `"cpu"` means something took the GPU before the service started:
   ask the user to run `stop.bat` and then `run.bat` on WIN.

4. **[Done on the M5, Nov 19, except the stop.bat fallback check, which needs a person on WIN: run_audio/run_code via WIN passed; `data/config.local.yaml` made; `/status` shows audio and sandbox served by WIN; voice and code entries through the orchestrator came back from WIN]** **Use it, then prove it.** First without editing anything:

   ```bash
   .venv/bin/python scripts/run_audio.py data/practice-pack/audio/p_aud_001.wav --win http://<WIN-ADDR>
   .venv/bin/python scripts/run_code.py "Plot y = x^2 for x in 0..10 and print the max" --win http://<WIN-ADDR>
   ```

   The audio result should show node `WIN`, and the code result `sandbox_node` `WIN` with the
   coder on `M5`. Then give the orchestrator the address without touching the tracked config
   (the tests and eval need `WIN_IP` to stay in `backend/config.yaml`, and the address changes
   with the network, so it must never be committed):

   ```bash
   cp backend/config.yaml data/config.local.yaml    # data/ is gitignored
   # in data/config.local.yaml set   nodes.win.service: http://<WIN-ADDR>:8001
   # and leave nodes.win.ollama as http://WIN_IP:11434 (nothing routes there any more)
   BENCHLOG_CONFIG=data/config.local.yaml .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
   curl -s http://localhost:8000/status             # audio and sandbox: "serving": "WIN"
   ```

   Re-copy the file whenever `backend/config.yaml` changes. Then check the fallback: ask the
   user to run `stop.bat` on WIN, capture a voice note, and confirm the entry comes back from
   the M5 marked as a fallback; then `run.bat` again. If there is time, rerun the eval with WIN
   connected so the latency table in `eval/results.md` shows audio served by WIN (slide
   material; optional). **At the demo venue the address is different: repeat items 3 and 4
   there.** It takes a minute.

5. **[Looks done: port 8001 is reachable from the M5 on the home network]** **A person, on the Windows laptop, once:** right-click
   `backend\services\win\open_firewall.bat` and choose "Run as administrator". Neither Claude
   can do this (it needs an administrator prompt). `net_info.bat` shows whether it is done.

6. **Pick up the photo fixes (branch `e2e-fixes`, written on WIN on Nov 19).** They change
   M5-owned files: `backend/pipelines/vision.py`, `backend/router.py`, `backend/config.yaml`
   (new `vision.zoom` block) and the frontend. After the PR is merged: `git pull`, re-copy
   `config.yaml` to `data/config.local.yaml` as in item 4 (or just add the `vision.zoom` block
   there), then `./scripts/start_m5.sh --stop` and `./scripts/start_m5.sh`. Until the
   orchestrator restarts, the M5 still answers burette-style readings wrongly. What was checked
   from WIN, against the M5's Ollama, on the photos in the untracked `lab-data/` folder (15
   questions with known answers): 13 right before, 14 right after; both burette readings are
   now right (4.2 mL, between 4 and 5; it said 6.5 before). The one miss lists the scale numbers
   and leaves out a faint "5". Cost: a question that triggers the look-closer pass takes
   14–18 s instead of 3–9 s; other questions are unchanged. Not checked, and yours to run:
   `eval/run_eval.py` on the practice pack (image rows only matter here), and one photo
   question in the UI to see the "Looked closer at this part of the photo" crop. If the eval
   gets worse or the demo feels slow, set `vision.zoom.enabled: false`; nothing else depends
   on it.

**Demo-day order.** Two cases:
- *Both laptops at the venue, same network:* WIN first: join the network, `run.bat` (before
  anything else can take the GPU), then `net_info.bat`, which should end with "Nothing left to
  do on this laptop." Ollama is not needed on WIN. Then on the M5: `./scripts/start_m5.sh`. It
  finds WIN by its mDNS name, writes the new address to `data/config.local.yaml` and prints
  which node serves each job. If it reports single-laptop mode, mDNS is blocked: ask the user
  for the address `net_info.bat` shows, put it in `data/config.local.yaml`, and run it again.
- *WIN stays at home, only the M5 goes to the venue (likely):* nothing to do on WIN. On the M5:
  `./scripts/start_m5.sh`. WIN does not answer, so it starts in single-laptop mode on the tracked
  config: every job on the M5, no WIN probes, and the status panel shows WIN offline with
  audio/sandbox "M5 (fallback)", which is the required fallback working. Never tunnel to the
  home network over the internet: the hard rules forbid calls outside the LAN, and judges test
  with Wi-Fi off. The eval in `eval/results.md` was run in exactly this mode.

From the M5, do not edit anything under `backend/services/win/`. If something there looks
wrong, tell the user what and why; it gets fixed from the WIN laptop.

## Architecture

```
React PWA (laptop + phone over LAN)
        │
FastAPI orchestrator (M5) ── routes by file type, NOT by LLM
        ├── vision    → Qwen3-VL 8B Instruct (images, video frames, doc Q&A)
        ├── audio     → Whisper large-v3-turbo + AST sound classifier
        ├── coder     → Qwen2.5-Coder 7B (M5) + sandboxed execution (WIN, fallback M5)
        └── docs      → nomic-embed-text + Chroma, grounded answers
        │
SQLite notebook (hash-chained entries) + local media folder
```

### Nodes (two laptops; there is no M1 node)

| Node | Hardware | Runs | Owns (edits) |
|---|---|---|---|
| **M5** (primary) | MacBook Air M5, 24 GB, macOS, fanless | Orchestrator, frontend, Qwen3-VL 8B Instruct, Qwen2.5-Coder 7B, nomic-embed-text, Chroma, SQLite. Also the local fallback for EVERY job. | everything outside `backend/services/win/` |
| **WIN** | i9-12900H, RTX 3060 6 GB, 16 GB RAM, Windows | WIN service on :8001: Whisper on CUDA + AST (audio) and the code sandbox. No Ollama needed. | `backend/services/win/` |

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
  main.py          # FastAPI app: /entry, /entries (GET, DELETE one), /transcribe, /verify, /status, /export, /protocols, /experiments, /media, /client-log
  events.py        # append-only event log, data/logs/events.jsonl
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

# run: one command; picks two-laptop or single-laptop mode by itself (scripts/pick_config.py)
./scripts/start_m5.sh            # Ollama (if not running) + orchestrator + frontend, logs in data/logs/
./scripts/start_m5.sh --solo     # force single-laptop mode;  --stop  stops orchestrator + frontend
# the same by hand (three terminals):
OLLAMA_HOST=0.0.0.0 OLLAMA_KEEP_ALIVE=-1 OLLAMA_MAX_LOADED_MODELS=3 ollama serve
BENCHLOG_CONFIG=$(.venv/bin/python scripts/pick_config.py) .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
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
start_ollama.bat     :: optional: Ollama on 0.0.0.0:11434 (only if the coder is routed to WIN)
run.bat              :: WIN service on :8001 (sets RUN_CODE_CLIENTS=lan)
net_info.bat         :: this laptop's name/IP on the current network, checks, the address for the M5
.venv\Scripts\python.exe check_node.py   :: smoke test; writes test_results.md
```

`/run_code` only answers clients allowed by `RUN_CODE_CLIENTS`: IPs, `lan` (private addresses
on the same /24 as the WIN laptop; what `run.bat` sets) or `*`. A client that is not allowed
gets 403 and its code jobs silently fall back to the M5.

### Connecting the two (and moving to another network)

`scripts/start_m5.sh` does the M5 side of this automatically: it uses `data/config.local.yaml`
if WIN answers at the address there, else looks WIN up by `discovery.win_hostname` (mDNS) and
rewrites that file, else starts in single-laptop mode on `backend/config.yaml`. It regenerates
the local file from the tracked config every time, so the copy never goes stale.

Own router or phone hotspot, never venue Wi-Fi. Nothing on the WIN laptop is tied to an IP, so
it needs no edits on a new network; run `net_info.bat` there to check it. The M5 needs the WIN
address in `nodes.win.service`. Put it in a local copy of the config, not in the tracked file
(the tests and eval expect the `WIN_IP` placeholder there, and the address changes with the
network): `cp backend/config.yaml data/config.local.yaml`, edit the copy, and start the
orchestrator with `BENCHLOG_CONFIG=data/config.local.yaml`. Then
`GET http://<M5-IP>:8000/status` should show `"serving": "WIN"` for audio and sandbox.

The address is either what `net_info.bat` prints (always works) or the WIN laptop's mDNS name,
`laptop-8k7cobtd.local` (the same on every network, but only where mDNS passes between
devices). With a name that does not resolve, each health probe waits on DNS for several
seconds instead of the 2 s connect timeout, so prefer the address when WIN may be absent.

## Logs and debugging (M5)

When the user reports a problem, look here first, before guessing:

- `.venv/bin/python scripts/diagnose.py [--hours N] [--all]`: one-screen summary of server starts
  and their mode, node up/down changes, failed/rejected captures with the end of the traceback,
  WIN->M5 fallbacks, browser-side errors, latency per entry type, and live `/status` + `/verify`.
- `data/logs/events.jsonl` (`backend/events.py`): one JSON line per event: `server_start`,
  `node_up`/`node_down`, `entry` (type, node, route, seconds, fallbacks, per-job nodes),
  `entry_rejected` (400s), `entry_error` (crashes, with traceback), `client_error` (what the
  browser hit: failed uploads, microphone, unreachable server; sent to `POST /client-log`).
- `data/logs/api.log`: uvicorn + pipeline logs (every job's node and latency), full tracebacks.
  `data/logs/frontend.log`: Vite. Both are appended across restarts, with a marker per start.
- The notebook itself: each entry's `details` holds per-step latencies, nodes and fallback errors.

All of `data/` is gitignored. Tests redirect the event log to a temp folder (`tests/conftest.py`).
On WIN, the service logs to its console; `check_node.py` and `net_info.bat` are the checks there.

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

Two routes were added on Nov 20; neither changes the entry shape:

- `DELETE /entries/{id}` takes an entry, and any follow-ups asked about it, out of the notebook.
  No row is removed. It appends a `note` entry with `details.kind == "deletion"` and
  `details.deleted` (a list of `{id, type, created_at, hash}`) and returns it. From then on
  `GET /entries`, `/export` and the experiment counts leave the named entries out
  (`Store.list_entries(include_deleted=True)` still returns them), and `/verify` still passes.
  404 for an unknown or already deleted id, 400 for a deletion record itself.
- `POST /transcribe` (multipart `file`) returns `{text, node, latency_s}` and creates no entry.
  The capture bar uses it to dictate a note into the text box.

Voice entries may also carry `details.unconfirmed_transcript`: words Whisper produced that the
no-speech filters did not trust. The card shows them as low confidence; they are never used for
the summary or for answers.

The M5 ↔ WIN contract is in `docs/win-service-contract.md`; extra response keys are allowed,
renaming or removing keys is not.

## Pipeline requirements

- **Image:** describe the image, answer follow-ups (`follow_up_of` = a photo or video entry id;
  the stored media plus the thread's earlier Q&A go back to the VLM; the new entry records
  `follow_up_of`, `thread_root` and `history` in `details`). Every follow-up is its own
  hash-chained entry; the frontend groups entries by `thread_root` (`frontend/src/threads.ts`)
  and shows them inside the photo's or video's card, with the follow-up box in that card. For
  colony counts, run the OpenCV blob count alongside the VLM and return both. Never present a
  VLM count alone as exact.
- **Look closer (photos):** a question about a reading, label or other fine detail
  (`DETAIL_RE` in `vision.py`) first asks the VLM for the bounding box of the feature that
  decides the answer (Qwen3-VL returns 0–1000 coordinates), cuts that region from the
  full-resolution original, and sends it as a second image with the answer call. The entry
  gets `details.zoom` (`box`, `crop_path`, `latency_s`) and the crop as an image artifact.
  Skipped for counting and colony questions, when no box comes back, and when the box covers
  more than `vision.zoom.max_area_frac` of the photo. `vision.zoom.enabled: false` turns it off.
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
- **Deleting:** never delete or update a row in `entries`; that breaks every hash after it.
  The Delete button calls `DELETE /entries/{id}`, which appends a deletion record (see the API
  section). Do not add a way to delete a deletion record, and do not remove media files on
  delete: the entry's hash covers their paths, and "what was deleted" must stay answerable.

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
- Windows firewall must allow port 8001 for the LAN (11434 only if Ollama is ever used on WIN).
- The RTX 3060's 6 GB cannot hold Whisper and Qwen2.5-Coder 7B together at `num_ctx` 16384.
  Measured on WIN: with both loaded the coder runs 48% on the GPU at 12.5 tok/s (50 s cold
  load); alone it reaches 26 tok/s, but Whisper on the CPU then takes 19 s for a 10 s clip.
  So the coder belongs on the M5 (`routing.coder: m5`) and WIN keeps audio and the sandbox.
- Don't use venue Wi-Fi (client isolation). Use our own router, switch, or a phone hotspot,
  with fixed IPs.
- VLMs are unreliable at counting; that's why the OpenCV count exists.
- Use `qwen3-vl:8b-instruct`, not `qwen3-vl:8b`: the plain tag is the thinking variant and
  ignores `think=false` (2-3x slower).
- Ollama resizes every image to ~1k tokens (~10 s prefill each on the M5) regardless of input
  size, so shrinking frames does not speed up video; fewer images does (`video.mode: sheets`).
  That holds up to about 1024 px on the long side. Above it the token count grows (measured on
  the M5: 1,052 tokens at 1024 px, 2,324 at 2048 px in 24 s, 4,015 at 3000 px in 59 s), and
  two such requests in a row stalled the M5 for about two minutes. Do not raise
  `vision.max_side` to make small print readable; that is what `vision.zoom` is for.
- At `vision.max_side` a phone photo of a burette loses the scale: the model read 6.5 mL for a
  meniscus at 4.3. Readings, labels and displays need the look-closer pass.
- Ollama reloads a model whenever `num_ctx` changes. Keep one `llm.num_ctx` for every call.
- Browsers only allow in-page microphone recording on https or localhost. On a phone over
  `http://<M5-IP>` the voice button opens the system recorder instead. The dictate button
  (speech into the text box) follows the same rule.

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
