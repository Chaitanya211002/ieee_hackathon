# WIN service contract

The Windows node runs a FastAPI service on port **8001**; no Ollama is needed there (the coder
model runs on the M5). The M5 orchestrator calls these endpoints. If any call fails or times
out, the M5 runs the job locally, so the WIN service must never be required for correctness.

- POST /transcribe (multipart file) -> {"text": str, "segments": [{"start","end","text"}], "language": str}
- POST /classify_sound (multipart file) -> {"labels": [{"label": str, "score": float}]}
- POST /run_code (json {"code": str, "files": {name: base64}}) ->
  {"stdout": str, "stderr": str, "exit_code": int, "artifacts": {name: base64}}
- GET /health -> {"ok": true}

## Notes for the implementer

- Multipart field name for `/transcribe` and `/classify_sound` is `file`. Inputs are WAV
  (16 kHz mono from the M5 for video audio; practice-pack audio is 16 kHz mono 16-bit PCM).
- `/classify_sound`: return the top labels sorted by score, descending (top 3 is enough).
  Model: `MIT/ast-finetuned-audioset-10-10-0.4593`. Scores are 0–1.
- `/transcribe`: Whisper large-v3-turbo via faster-whisper on CUDA (fall back to CPU int8).
  `segments` times are in seconds (floats).
- `/run_code`: write `files` (base64-decoded) into a fresh temp dir, write `code` to
  `main.py`, run it with a separate Python/venv, 20 s timeout, cwd = temp dir, no network.
  Return every `*.png` in the temp dir as `artifacts` (base64). On timeout return
  `exit_code: -1` and put "Timed out after 20 s" in `stderr`.
- Open the Windows firewall for TCP 8001 on the private network (`open_firewall.bat`).
