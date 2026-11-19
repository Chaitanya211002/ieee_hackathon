"""Run the image pipeline on one file.

.venv/bin/python scripts/run_vision.py data/practice-pack/image/p_img_002.jpg "How many people?"
.venv/bin/python scripts/run_vision.py plate.jpg "How many colonies?"
"""

import argparse

from _common import show

from backend.pipelines import vision

p = argparse.ArgumentParser()
p.add_argument("image")
p.add_argument("question", nargs="?")
p.add_argument("--colonies", action="store_true", help="force the OpenCV colony count")
a = p.parse_args()
show(vision.analyze(a.image, a.question, colonies=a.colonies or None))
