#!/usr/bin/env bash
# Start BenchLog on the M5: Ollama (if not running), the orchestrator and the frontend.
# Picks two-laptop or single-laptop mode by itself (scripts/pick_config.py), so the same
# command works at home with the WIN laptop and at a venue without it.
#
#   ./scripts/start_m5.sh          # auto
#   ./scripts/start_m5.sh --solo   # force single-laptop mode
#   ./scripts/start_m5.sh --stop   # stop the orchestrator and frontend (Ollama keeps running)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs

stop() {
  pkill -f "uvicorn backend.main:app" 2>/dev/null || true
  pkill -f "node .*vite --host" 2>/dev/null || true
  pkill -f "npm exec vite --host" 2>/dev/null || true
}
if [[ "${1:-}" == "--stop" ]]; then stop; echo "Stopped the orchestrator and frontend."; exit 0; fi

if ! curl -sf --max-time 2 http://localhost:11434/api/tags >/dev/null; then
  echo "Starting Ollama..."
  OLLAMA_HOST=0.0.0.0 OLLAMA_KEEP_ALIVE=-1 OLLAMA_MAX_LOADED_MODELS=3 nohup ollama serve </dev/null >data/logs/ollama.log 2>&1 &
  for _ in $(seq 1 30); do curl -sf --max-time 1 http://localhost:11434/api/tags >/dev/null && break; sleep 1; done
fi

CONFIG=$(.venv/bin/python scripts/pick_config.py "$@")
stop
sleep 1
# Logs are appended (never overwritten) so earlier runs stay available for debugging.
for f in api frontend; do echo "===== start $(date '+%Y-%m-%d %H:%M:%S') config=${CONFIG#$PWD/} =====" >>"data/logs/$f.log"; done
# Every launched process gets its own stdin/stdout/stderr, so nothing holds this script's output open.
BENCHLOG_CONFIG="$CONFIG" nohup .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000 </dev/null >>data/logs/api.log 2>&1 &
(cd frontend && exec nohup npx vite --host </dev/null >>../data/logs/frontend.log 2>&1) &
for _ in $(seq 1 40); do curl -sf --max-time 1 http://localhost:5173/api/health >/dev/null && break; sleep 1; done

echo
curl -s http://localhost:8000/status | .venv/bin/python -c "
import json, sys
s = json.load(sys.stdin)
print('Jobs: ' + ', '.join(f'{j} -> {v[\"serving\"]}' for j, v in s['jobs'].items()))"
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
echo "BenchLog is up:  http://localhost:5173${IP:+   phone: http://$IP:5173}"
echo "Config: ${CONFIG#$PWD/}   Logs: data/logs/   Problems: .venv/bin/python scripts/diagnose.py"
