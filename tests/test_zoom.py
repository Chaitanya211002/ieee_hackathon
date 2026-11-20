"""The "look closer" pass in the vision pipeline, with the model stubbed out (no Ollama needed)."""

import base64

import cv2
import numpy as np
import pytest

from backend.config import get_config
from backend.pipelines import vision


@pytest.fixture
def photo(tmp_path):
    """A 2000x3000 photo with a small bright square, so a crop of it is easy to recognise."""
    img = np.full((3000, 2000, 3), 40, np.uint8)
    cv2.rectangle(img, (900, 1200), (1100, 1400), (255, 255, 255), -1)
    path = tmp_path / "photo.jpg"
    cv2.imwrite(str(path), img)
    return path


@pytest.fixture
def chat(monkeypatch):
    """Replace the model: the first reply is the locate answer, the second the real answer."""
    calls = []
    replies = ['{"feature": "the liquid surface", "bbox_2d": [450, 400, 550, 470]}', "It reads 4.4 mL."]

    def fake(node, model, messages, **kwargs):
        calls.append(messages)
        return replies[min(len(calls), len(replies)) - 1]

    monkeypatch.setattr(vision.nodes, "chat", fake)
    fake.calls, fake.replies = calls, replies
    return fake


def _decode(b64):
    return cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)


def test_parse_bbox():
    assert vision.parse_bbox('```json\n{"bbox_2d": [417, 387, 607, 432], "label": "meniscus"}\n```') == (
        0.417, 0.387, 0.607, 0.432,
    )  # fmt: skip
    assert vision.parse_bbox("[607, 432, 417, 387]") == (0.417, 0.387, 0.607, 0.432)  # corners swapped
    assert vision.parse_bbox("[-20, 0, 1200, 999]") == (0.0, 0.0, 1.0, 0.999)  # clamped to the image
    assert vision.parse_bbox("I cannot tell.") is None
    assert vision.parse_bbox("[500, 500, 501, 501]") is None  # too small to be a region


def test_crop_box_margin_and_whole_image():
    zoom = {"margin": 0.5, "min_margin": 0.08, "max_area_frac": 0.5}
    x1, y1, x2, y2 = vision.crop_box((0.45, 0.40, 0.55, 0.47), zoom)
    assert (round(x1, 2), round(x2, 2)) == (0.37, 0.63)  # the 8% minimum margin wins over 50% of a small box
    assert (round(y1, 2), round(y2, 2)) == (0.32, 0.55)
    assert vision.crop_box((0.4, 0.0, 0.6, 1.0), zoom) == pytest.approx((0.3, 0.0, 0.7, 1.0))  # clamped at the edges
    assert vision.crop_box((0.1, 0.1, 0.9, 0.9), zoom) is None  # most of the image: no point zooming


def test_question_gets_a_full_resolution_crop(photo, chat):
    r = vision.analyze(photo, "What is the burette reading?")
    assert r["answer"] == "It reads 4.4 mL." and len(chat.calls) == 2
    locate, answer = chat.calls
    assert "Do not answer yet" in locate[-1]["content"] and len(locate[-1]["images"]) == 1
    assert answer[0] == locate[0]  # same system prompt, so the image tokens are cached
    assert answer[-1]["images"][0] == locate[-1]["images"][0]
    assert answer[-1]["content"].startswith(vision.ZOOM_NOTE) and answer[-1]["content"].endswith("burette reading?")
    full, crop = (_decode(b) for b in answer[-1]["images"])
    assert max(full.shape[:2]) == get_config()["vision"]["max_side"]
    # box 0.37-0.63 x 0.32-0.55 of 2000x3000 is about 520x690 px: cut from the original, not from
    # the downscaled copy (where it would be about 177x235)
    assert crop.shape[0] == pytest.approx(690, abs=2) and crop.shape[1] == pytest.approx(520, abs=2)
    assert crop[345, 260].min() > 200 and crop[5, 5].max() < 80  # the bright square is in the middle
    saved = cv2.imread(r["zoom"]["crop_path"])
    assert saved.shape == crop.shape and r["zoom"]["box"] == pytest.approx([0.37, 0.32, 0.63, 0.55])


def test_no_zoom_without_a_detail_question_or_for_counting(photo, chat):
    chat.replies[:] = ["A photo of a bench."]
    assert "zoom" not in vision.analyze(photo) and len(chat.calls) == 1  # no question
    assert "zoom" not in vision.analyze(photo, "What colour is the liquid?")  # nothing small to read
    assert "zoom" not in vision.analyze(photo, "How many colonies are on this plate?", colonies=False)
    assert "zoom" not in vision.analyze(photo, "Count the number of tubes")  # counting needs the whole image
    assert len(chat.calls) == 4 and all(len(c[-1]["images"]) == 1 for c in chat.calls)


@pytest.mark.parametrize(
    "question",
    ["What is the burette reading?", "at what marking is the liquid at ?", "What does the label say?",
     "What temperature is displayed?", "How much liquid is in the flask?", "What is the lot number?"],
)  # fmt: skip
def test_detail_questions_trigger_the_zoom(question):
    assert vision.DETAIL_RE.search(question)


def test_falls_back_to_a_plain_answer(photo, chat, monkeypatch):
    chat.replies[:] = ["I cannot give a box.", "It says 250 ml."]
    r = vision.analyze(photo, "What does the label say?")
    assert r["answer"] == "It says 250 ml." and "zoom" not in r and len(chat.calls[1][-1]["images"]) == 1

    chat.calls.clear()
    chat.replies[:] = ['{"feature": "the label", "bbox_2d": [0, 0, 1000, 1000]}', "It says 250 ml."]  # whole image
    assert "zoom" not in vision.analyze(photo, "What does the label say?")

    chat.calls.clear()
    monkeypatch.setitem(get_config()["vision"]["zoom"], "enabled", False)
    chat.replies[:] = ["It says 250 ml."]
    assert "zoom" not in vision.analyze(photo, "What does the label say?") and len(chat.calls) == 1


def test_follow_up_puts_the_crop_on_the_new_question(photo, chat):
    history = [{"question": "What is this?", "answer": "A burette."}]  # asked without a zoom
    vision.analyze(photo, "What is the reading?", history=history)
    answer = chat.calls[1]
    assert [m["role"] for m in answer] == ["system", "user", "assistant", "user"]
    assert len(answer[1]["images"]) == 1 and answer[1]["content"] == "What is this?"
    assert len(answer[3]["images"]) == 1 and answer[3]["content"].startswith(vision.ZOOM_NOTE)
