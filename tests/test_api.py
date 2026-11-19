"""End-to-end API tests: every endpoint, real pipelines, practice-pack samples.

Needs Ollama on the M5 and data/practice-pack. The WIN node is unconfigured (WIN_IP), so every
job runs on the M5, except in test_voice_served_by_win, which points WIN at a WIN service on
127.0.0.1:8001 if one is running.
"""

import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import nodes, store
from backend.config import get_config
from backend.pipelines import docs
from backend.store import Store
from tests.conftest import PACK, needs_ollama, needs_pack

pytestmark = [needs_ollama, needs_pack]

CONTRACT = {"id", "type", "created_at", "summary", "details", "artifacts", "hash", "prev_hash", "node"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    mp = pytest.MonkeyPatch()
    mp.setattr(store, "_default", Store(tmp / "t.sqlite3", tmp / "media"))
    mp.setitem(get_config()["paths"], "chroma", str(tmp / "chroma"))
    mp.setitem(get_config()["llm"], "warmup", False)
    docs._chroma.clear()
    nodes._status.clear()
    from backend.main import app

    with TestClient(app) as c:
        yield c
    docs._chroma.clear()
    mp.undo()


def _post(client, path=None, **form):
    files = None
    if path is not None:
        files = {"file": (path.name, path.read_bytes(), form.pop("mime", None) or "application/octet-stream")}
    r = client.post("/entry", data=form, files=files)
    assert r.status_code == 200, r.text
    e = r.json()
    assert set(e) == CONTRACT
    assert len(e["hash"]) == 64 and len(e["prev_hash"]) == 64
    return e


def test_health_and_status(client):
    assert client.get("/health").json()["ok"]
    s = client.get("/api/status").json()
    assert set(s["jobs"]) == {"vision", "docs", "coder", "audio", "sandbox"}
    assert all(j["serving"] == "M5" for j in s["jobs"].values())  # WIN not configured
    assert s["nodes"]["m5.ollama"]["up"]


def test_photo(client):
    e = _post(client, PACK / "image" / "p_img_012.jpg", text="How many cats are in this image?", mime="image/jpeg")
    assert e["type"] == "photo" and e["node"] == "M5"
    assert e["details"]["vlm_count_estimate"] == 2
    assert "estimate" in e["summary"]
    img = e["artifacts"][0]
    assert img["kind"] == "image" and client.get(img["path"]).status_code == 200


def test_voice(client):
    e = _post(client, PACK / "audio" / "p_aud_007.wav", question="Where was his country home?", mime="audio/wav")
    assert e["type"] == "voice"
    assert "essex" in e["details"]["answer"].lower()
    assert len(e["details"]["sound_labels"]) == 3
    assert any(a["kind"] == "transcript" for a in e["artifacts"])


def test_video(client):
    e = _post(client, PACK / "video" / "p_vid_005.mp4", text="Does the bar get taller or shorter?", mime="video/mp4")
    assert e["type"] == "video"
    assert "taller" in e["details"]["answer"].lower()
    assert len(e["details"]["frames"]) == get_config()["video"]["max_frames"]
    assert client.get(e["details"]["frames"][0]["path"]).status_code == 200


def test_pdf_with_question_then_text_questions(client):
    e = _post(client, PACK / "text" / "p_txt_doc_04.pdf", text="What fish living in the Amazon river is known to bite humans?",
              mime="application/pdf")  # fmt: skip
    assert e["type"] == "protocol_qa" and not e["details"]["refused"]
    assert "piranha" in e["details"]["answer"].lower()
    assert e["details"]["citation"]["source"] == "p_txt_doc_04.pdf"

    e = _post(client, text="4380 species of what have been registered?")
    assert e["type"] == "protocol_qa" and e["details"]["refused"]
    assert e["summary"] == "Not in your indexed protocols."


def test_protocol_upload_and_list(client):
    p = PACK / "text" / "p_txt_doc_02.txt"
    r = client.post("/protocols", files={"file": (p.name, p.read_bytes(), "text/plain")})
    assert r.status_code == 200 and r.json()["chunks"] >= 1
    assert {x["source"] for x in client.get("/protocols").json()} >= {"p_txt_doc_02.txt", "p_txt_doc_04.pdf"}
    assert client.post("/protocols", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400


def test_code_text(client):
    e = _post(client, text="code: print the first 10 square numbers, one per line")
    assert e["type"] == "analysis"
    assert e["details"]["ok"] and e["details"]["executed"] and "81" in e["details"]["stdout"]
    assert any(a["kind"] == "code" for a in e["artifacts"])


def test_csv_analysis_with_plot(client, tmp_path):
    csv = tmp_path / "od600.csv"
    csv.write_text("time_h,od600\n0,0.05\n1,0.09\n2,0.18\n3,0.35\n4,0.62\n5,0.95\n")
    e = _post(client, csv, text="Plot OD600 against time and print the doubling time in hours", mime="text/csv")
    assert e["type"] == "analysis" and e["details"]["ok"]
    plots = [a for a in e["artifacts"] if a["kind"] == "plot"]
    assert plots and client.get(plots[0]["path"]).content[:4] == b"\x89PNG"


def test_note(client):
    e = _post(client, text="Added 5 uL lysis buffer to row A; incubating 10 min at RT")
    assert e["type"] == "note" and e["summary"].startswith("Added 5 uL")


def test_bad_requests(client):
    assert client.post("/entry", data={}).status_code == 400
    r = client.post("/entry", files={"file": ("x.bin", b"\x00\x01", "application/octet-stream")})
    assert r.status_code == 400
    assert client.get("/media/../../etc/passwd").status_code == 404


def test_entries_experiments_export_verify(client):
    exp = client.post("/experiments", data={"name": "Gel run 3"}).json()
    _post(client, text="note: gel loaded", experiment_id=exp["id"])
    assert [e["summary"] for e in client.get("/entries", params={"experiment_id": exp["id"]}).json()] == ["gel loaded"]
    all_entries = client.get("/entries").json()
    assert len(all_entries) >= 8
    today = all_entries[0]["created_at"][:10]
    assert len(client.get("/entries", params={"date": today}).json()) == len(all_entries)

    v = client.get("/verify").json()
    assert v["ok"] and v["verified"] == len(all_entries)

    md = client.get("/export", params={"date": today}).text
    assert md.startswith("# BenchLog lab log") and all_entries[-1]["hash"] in md
    assert "Hash chain: verified" in md


def _win_service_up() -> bool:
    try:
        return httpx.get("http://127.0.0.1:8001/health", timeout=2).json().get("ok") is True
    except Exception:
        return False


@pytest.mark.skipif(not _win_service_up(), reason="no WIN service on 127.0.0.1:8001")
def test_voice_served_by_win_and_fallback(client, monkeypatch):
    monkeypatch.setitem(
        get_config()["nodes"], "win", {"ollama": "http://127.0.0.1:11434", "service": "http://127.0.0.1:8001"}
    )
    nodes._status.clear()
    e = _post(client, PACK / "audio" / "p_aud_002.wav", text="Transcribe this audio.", mime="audio/wav")
    assert e["node"] == "WIN" and "wind" in e["details"]["transcript"].lower()
    assert client.get("/status").json()["jobs"]["audio"]["serving"] == "WIN"

    # unplug WIN: same request falls back to the M5
    monkeypatch.setitem(get_config()["nodes"], "win", {"ollama": "http://127.0.0.1:9", "service": "http://127.0.0.1:9"})
    nodes._status.clear()
    e = _post(client, PACK / "audio" / "p_aud_002.wav", text="Transcribe this audio.", mime="audio/wav")
    assert e["node"] == "M5" and "wind" in e["details"]["transcript"].lower()


def test_photo_follow_up(client):
    parent = _post(client, PACK / "image" / "p_img_012.jpg", text="How many cats are in this image?", mime="image/jpeg")
    e = _post(client, text="What are they lying on?", follow_up_of=parent["id"])
    d = e["details"]
    assert e["type"] == "photo" and d["follow_up_of"] == parent["id"] and d["thread_root"] == parent["id"]
    assert d["history"][0]["question"] == "How many cats are in this image?"
    assert d["answer"] and d["question"] == "What are they lying on?"
    assert e["artifacts"][0]["path"] == parent["artifacts"][0]["path"]  # reuses the stored photo

    # a follow-up to the follow-up carries the whole thread
    e2 = _post(client, text="Is either cat asleep?", follow_up_of=e["id"])
    assert e2["details"]["thread_root"] == parent["id"] and len(e2["details"]["history"]) == 2


def test_video_follow_up(client):
    parent = next(x for x in client.get("/entries").json() if x["type"] == "video")
    e = _post(client, text="What colour is the bar?", follow_up_of=parent["id"])
    assert e["type"] == "video" and e["details"]["follow_up_of"] == parent["id"]
    assert "blue" in e["details"]["answer"].lower()


def test_follow_up_errors(client):
    note = _post(client, text="note: follow-up target")
    assert client.post("/entry", data={"text": "why?", "follow_up_of": note["id"]}).status_code == 400
    assert client.post("/entry", data={"text": "why?", "follow_up_of": "nope"}).status_code == 400


def test_verify_catches_tampering(client):
    entries = client.get("/entries").json()
    db = store.get_store().db_path
    c = sqlite3.connect(db)
    c.execute("UPDATE entries SET summary = 'tampered' WHERE id = ?", (entries[1]["id"],))
    c.commit()
    c.close()
    v = client.get("/verify").json()
    assert not v["ok"] and v["first_broken"] == entries[1]["id"]
    assert "BROKEN" in client.get("/export").text
