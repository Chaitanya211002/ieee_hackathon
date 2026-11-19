import wave

import numpy as np

from backend import nodes
from backend.pipelines import audio
from tests.conftest import PACK, needs_ollama, needs_pack


def _silence(tmp_path):
    p = tmp_path / "silence.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.zeros(16000 * 3, np.int16).tobytes())
    return p


def test_local_silence_has_no_text(tmp_path):
    nodes._status.clear()
    r = audio.analyze(_silence(tmp_path))
    assert r["transcript"] == "" and r["node"] == "M5"
    assert r["summary"].startswith("No speech")


@needs_pack
def test_local_speech_and_labels():
    r = audio.analyze(PACK / "audio" / "p_aud_002.wav", "Transcribe this audio.")
    assert "wind being adverse" in r["transcript"].lower()
    assert r["answer"] == r["transcript"]
    assert len(r["sound_labels"]) == 3 and r["speech_detected"]


@needs_pack
def test_summary_only_shows_confident_sounds():
    r = audio.analyze(PACK / "audio" / "p_aud_018.wav")  # rooster
    assert all(a["score"] >= 0.5 for a in r["sound_alerts"])
    for lab in r["sound_labels"]:
        if lab["score"] < 0.5:
            assert lab["label"] not in r["summary"]


@needs_ollama
@needs_pack
def test_question_about_sound():
    r = audio.analyze(PACK / "audio" / "p_aud_015.wav", "What sound is this?")
    assert "dog" in r["answer"].lower()
