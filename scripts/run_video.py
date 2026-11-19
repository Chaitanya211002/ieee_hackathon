"""Run the video pipeline on one file.

.venv/bin/python scripts/run_video.py data/practice-pack/video/p_vid_002.mp4 "Which direction does the square move?"
"""

import argparse

from _common import show

from backend.pipelines import video

p = argparse.ArgumentParser()
p.add_argument("video")
p.add_argument("question", nargs="?")
p.add_argument("--out", help="where to keep the frames")
a = p.parse_args()
show(video.analyze(a.video, a.question, a.out))
