#!/usr/bin/env bash
# One-time (online) setup of the M5's code sandbox: a separate venv with numpy, pandas and
# matplotlib, plus the network guard. Path comes from sandbox.local_python in config.yaml.
set -euo pipefail
cd "$(dirname "$0")/.."
VENV=data/sandbox_venv
python3.11 -m venv "$VENV"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q numpy pandas matplotlib
SITE=$("$VENV/bin/python" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
cp backend/sandbox/guard.py "$SITE/benchlog_sandbox_guard.py"
echo "import benchlog_sandbox_guard" > "$SITE/benchlog_sandbox.pth"
MPLCONFIGDIR="$PWD/$VENV/.mplconfig" MPLBACKEND=Agg "$VENV/bin/python" -c "import matplotlib.pyplot"
echo "Sandbox ready: $VENV"
