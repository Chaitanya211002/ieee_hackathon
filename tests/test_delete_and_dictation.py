"""Deleting entries, dictation, and the voice transcript. No model is needed for any of these."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import store as store_mod
from backend.config import get_config
from backend.pipelines import audio
from backend.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.sqlite3", tmp_path / "media")


def _thread(store):
    """A note, then a photo with two follow-ups, then another note."""
    a = store.add_entry(type="note", summary="first")
    photo = store.add_entry(type="photo", summary="flask")
    f1 = store.add_entry(
        type="photo", summary="colour?", details={"follow_up_of": photo["id"], "thread_root": photo["id"]}
    )
    f2 = store.add_entry(
        type="photo", summary="volume?", details={"follow_up_of": f1["id"], "thread_root": photo["id"]}
    )
    b = store.add_entry(type="note", summary="last")
    return a, photo, f1, f2, b


def test_delete_hides_the_entry_and_keeps_the_chain(store):
    a, photo, f1, f2, b = _thread(store)
    record = store.delete_entry(a["id"])
    assert record["type"] == "note" and record["details"]["kind"] == "deletion"
    assert record["details"]["deleted"] == [
        {"id": a["id"], "type": "note", "created_at": a["created_at"], "hash": a["hash"]}
    ]
    assert record["prev_hash"] == b["hash"]  # the deletion is the newest link in the chain
    shown = [e["id"] for e in store.list_entries()]
    assert a["id"] not in shown and record["id"] in shown and photo["id"] in shown
    assert len(store.list_entries(include_deleted=True)) == 6  # no row was removed
    assert store.verify_report() == {**store.verify_report(), "ok": True, "entries": 6, "verified": 6}


def test_deleting_a_capture_takes_its_follow_ups_with_it(store):
    _, photo, f1, f2, _ = _thread(store)
    record = store.delete_entry(photo["id"])
    assert [d["id"] for d in record["details"]["deleted"]] == [photo["id"], f1["id"], f2["id"]]
    assert "2 follow-ups" in record["summary"]
    assert {e["summary"] for e in store.list_entries()} == {"first", "last", record["summary"]}
    assert store.verify_chain() is None


def test_delete_errors(store):
    a, *_ = _thread(store)
    record = store.delete_entry(a["id"])
    with pytest.raises(KeyError):
        store.delete_entry(a["id"])  # already deleted
    with pytest.raises(KeyError):
        store.delete_entry("nope")
    with pytest.raises(ValueError):
        store.delete_entry(record["id"])  # the record of a deletion stays


def test_experiment_count_leaves_out_deleted_entries(store):
    a, photo, *_ = _thread(store)
    count = lambda: next(e for e in store.list_experiments() if e["id"] == "default")["entry_count"]  # noqa: E731
    assert count() == 5
    store.delete_entry(photo["id"])  # hides 3, adds 1 record
    assert count() == 3


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_default", Store(tmp_path / "t.sqlite3", tmp_path / "media"))
    monkeypatch.setitem(get_config()["llm"], "warmup", False)
    monkeypatch.setitem(get_config()["paths"], "logs", str(tmp_path / "logs"))
    from backend.main import app

    with TestClient(app) as c:
        yield c


def test_delete_api_and_export(client):
    st = store_mod.get_store()
    a, photo, f1, *_ = _thread(st)
    r = client.delete(f"/api/entries/{photo['id']}")
    assert r.status_code == 200 and r.json()["details"]["kind"] == "deletion"
    ids = [e["id"] for e in client.get("/api/entries").json()]
    assert photo["id"] not in ids and f1["id"] not in ids and a["id"] in ids
    assert client.get("/api/verify").json()["ok"] is True
    assert client.delete(f"/api/entries/{photo['id']}").status_code == 404
    assert client.delete(f"/api/entries/{r.json()['id']}").status_code == 400
    assert client.delete("/api/entries/nope").status_code == 404
    md = client.get("/api/export").text
    assert "- Deleted entries: 3" in md and "flask" not in md
    # a deleted photo can no longer be asked about
    r = client.post("/api/entry", data={"text": "what colour?", "follow_up_of": photo["id"]})
    assert r.status_code == 400


def test_transcribe_returns_text_and_creates_no_entry(client, monkeypatch, tmp_path):
    seen = {}

    def fake(path):
        seen["suffix"], seen["bytes"] = Path(path).suffix, Path(path).read_bytes()
        return {"text": "added three drops of indicator", "node": "WIN", "latency_s": 0.4, "segments": []}

    monkeypatch.setattr(audio, "transcribe", fake)
    r = client.post("/api/transcribe", files={"file": ("dictation.webm", b"not really audio", "audio/webm")})
    assert r.status_code == 200
    assert r.json() == {"text": "added three drops of indicator", "node": "WIN", "latency_s": 0.4}
    assert seen == {"suffix": ".webm", "bytes": b"not really audio"}
    assert client.get("/api/entries").json() == []
    assert client.post("/api/transcribe", files={"file": ("x.webm", b"", "audio/webm")}).status_code == 400


def _voice(monkeypatch, text, labels, **extra):
    monkeypatch.setattr(
        audio, "transcribe", lambda p: {"text": text, "segments": [], "node": "M5", "latency_s": 0.1, **extra}
    )
    monkeypatch.setattr(audio, "classify_sound", lambda p: {"labels": labels, "node": "M5", "latency_s": 0.1})
    return audio.analyze("clip.wav")


def test_voice_keeps_what_was_heard_when_the_filters_drop_it(monkeypatch):
    speech, noise = [{"label": "Speech", "score": 0.9}], [{"label": "Mechanical fan", "score": 0.7}]
    r = _voice(monkeypatch, "I added the buffer to the first row", speech)
    assert r["transcript"] == "I added the buffer to the first row" and "unconfirmed_transcript" not in r

    r = _voice(monkeypatch, "Thank you.", noise)  # a few words, no speech label: treated as a hallucination
    assert (
        r["transcript"] == "" and r["unconfirmed_transcript"] == "Thank you." and r["summary"].startswith("No speech")
    )

    r = _voice(monkeypatch, "", speech, dropped_text="testing one two")  # segments Whisper itself doubted
    assert r["transcript"] == "" and r["unconfirmed_transcript"] == "testing one two"
