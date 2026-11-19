import subprocess

import cv2
import numpy as np

from backend.config import get_config
from backend.pipelines import video
from tests.conftest import PACK, needs_ollama, needs_pack


def test_frame_times_cover_start_and_end():
    ts = video.frame_times(6.2)
    assert len(ts) == get_config()["video"]["max_frames"]
    assert ts[0] == 0.0 and ts[-1] >= 6.0
    assert ts == sorted(ts)


def test_frame_times_long_clip_capped():
    assert len(video.frame_times(30.0)) == get_config()["video"]["max_frames"]


def test_extract_and_sheets(tmp_path):
    src = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=10:duration=3", str(src)],
        check=True,
    )
    frames = video.extract_frames(src, tmp_path / "f")
    assert len(frames) == get_config()["video"]["max_frames"]
    img = cv2.imread(frames[0]["path"])
    assert max(img.shape[:2]) <= get_config()["video"]["max_side"]
    sheets = video.contact_sheets(frames, 5, 5)
    assert len(sheets) == 2
    sheet = cv2.imdecode(np.frombuffer(sheets[0], np.uint8), cv2.IMREAD_COLOR)
    assert sheet.shape[1] > sheet.shape[0] * 3  # five tiles side by side
    assert video.probe(src)["has_audio"] is False


@needs_ollama
@needs_pack
def test_video_answer_last_frame():
    r = video.analyze(PACK / "video" / "p_vid_010.mp4", "What color is the background at the end?")
    assert "blue" in r["answer"].lower()
    assert r["audio"] is None and len(r["frames"]) == get_config()["video"]["max_frames"]
