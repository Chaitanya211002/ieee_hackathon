"""Run the audio pipeline on one file.

    .venv/bin/python scripts/run_audio.py data/practice-pack/audio/p_aud_001.wav "What kind of day was it?"
    .venv/bin/python scripts/run_audio.py clip.wav --win http://127.0.0.1   # use a WIN node at this host
"""

import argparse

from _common import show

from backend.config import get_config
from backend.pipelines import audio

p = argparse.ArgumentParser()
p.add_argument("file")
p.add_argument("question", nargs="?")
p.add_argument("--win", help="override the WIN host, e.g. http://192.168.8.20")
a = p.parse_args()
if a.win:
    get_config()["nodes"]["win"] = {"ollama": f"{a.win}:11434", "service": f"{a.win}:8001"}
show(audio.analyze(a.file, a.question))
