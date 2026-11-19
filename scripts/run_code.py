"""Run the code pipeline on one prompt (optionally with input files).

    .venv/bin/python scripts/run_code.py "Plot y = x^2 for x in 0..10 and print the max"
    .venv/bin/python scripts/run_code.py "Fit a standard curve" --file plate.csv
    .venv/bin/python scripts/run_code.py "..." --win http://127.0.0.1   # use a WIN node at this host
"""

import argparse
from pathlib import Path

from _common import show

from backend.config import get_config
from backend.pipelines import code

p = argparse.ArgumentParser()
p.add_argument("prompt")
p.add_argument("--file", action="append", default=[])
p.add_argument("--win", help="override the WIN host, e.g. http://192.168.8.20")
a = p.parse_args()
if a.win:
    get_config()["nodes"]["win"] = {"ollama": f"{a.win}:11434", "service": f"{a.win}:8001"}
files = {Path(f).name: Path(f).read_bytes() for f in a.file}
show(code.generate(a.prompt, files=files))
