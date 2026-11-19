import cv2
import numpy as np

from backend.pipelines import vision
from tests.conftest import PACK, needs_ollama, needs_pack


def _plate(tmp_path, n, dark=True):
    rng = np.random.default_rng(0)
    img = np.full((600, 600, 3), 225 if dark else 40, np.uint8)
    cv2.circle(img, (300, 300), 280, (200, 200, 190) if dark else (60, 60, 60), -1)
    pts = []
    while len(pts) < n:
        p = rng.integers(80, 520, 2)
        if all(np.hypot(*(p - q)) > 30 for q in pts) and np.hypot(*(p - 300)) < 240:
            pts.append(p)
    for x, y in pts:
        cv2.circle(img, (int(x), int(y)), int(rng.integers(6, 11)), (90, 110, 120) if dark else (230, 230, 230), -1)
    path = tmp_path / "plate.jpg"
    cv2.imwrite(str(path), img)
    return path


def test_count_colonies_dark(tmp_path):
    r = vision.count_colonies(_plate(tmp_path, 23), tmp_path / "out.jpg")
    assert r["count"] == 23
    assert (tmp_path / "out.jpg").exists()


def test_count_colonies_light(tmp_path):
    assert vision.count_colonies(_plate(tmp_path, 15, dark=False))["count"] == 15


def test_first_int():
    assert vision.first_int("There are 4 zebras") == 4
    assert vision.first_int("Two people.") == 2
    assert vision.first_int("none visible") is None


@needs_ollama
@needs_pack
def test_vlm_counts_people():
    r = vision.analyze(PACK / "image" / "p_img_002.jpg", "How many people are in this image?")
    assert r["vlm_count_estimate"] == 2
    assert "estimate" in r["summary"]
    assert "opencv" not in r


@needs_ollama
def test_colony_question_returns_both(tmp_path):
    r = vision.analyze(_plate(tmp_path, 12), "How many colonies are on this plate?", out_dir=tmp_path)
    assert r["opencv"]["count"] == 12
    assert "vlm_count_estimate" in r
    assert "OpenCV count: 12" in r["summary"]
