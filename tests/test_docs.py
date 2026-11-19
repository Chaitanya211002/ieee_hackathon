import pytest

from backend.config import get_config
from backend.pipelines import docs
from tests.conftest import PACK, needs_ollama, needs_pack


def test_ungrounded_numbers():
    ctx = "an estimated 438,000 species were registered in 1999"
    assert docs.ungrounded_numbers("4380 species of what?", ctx) == ["4380"]
    assert docs.ungrounded_numbers("How many in 1999? About 438000.", ctx) == []


def test_text_sections_and_chunks(tmp_path):
    p = tmp_path / "proto.txt"
    p.write_text("PCR setup\n\n" + "Mix the master mix. " * 400 + "\n\nGel run\n\nLoad 5 uL per lane.\n")
    secs = docs.text_sections(p)
    assert [s["title"] for s in secs] == ["PCR setup", "Gel run"]
    chunks = docs.chunk_sections(secs, 500)
    assert all(len(c["text"].split()) <= 520 for c in chunks)
    assert {c["section"] for c in chunks} == {"PCR setup", "Gel run"}


@pytest.fixture
def fresh_index(tmp_path, monkeypatch):
    monkeypatch.setitem(get_config()["paths"], "chroma", str(tmp_path / "chroma"))
    docs._chroma.clear()
    yield
    docs._chroma.clear()


@needs_ollama
def test_empty_index_refuses(fresh_index):
    r = docs.ask("What is the annealing temperature?")
    assert r["refused"] and r["message"] == "Not in your indexed protocols."


@needs_ollama
@needs_pack
def test_answer_cite_and_refuse(fresh_index):
    info = docs.ingest(PACK / "text" / "p_txt_doc_01.pdf")
    assert info["chunks"] >= 1 and info["sections"] == ["French and Indian War"]
    assert docs.list_protocols()[0]["source"] == "p_txt_doc_01.pdf"

    r = docs.ask("Who defeated Montcalm at Quebec?")
    assert not r["refused"] and "wolfe" in r["answer"].lower()
    assert r["citation"]["section"] == "French and Indian War"

    # adversarial: the document has the battle in 1760, not 1706
    r = docs.ask("What battle outside Quebec City did British lose in 1706?")
    assert r["refused"] and r["answer"] is None and r["message"] == "Not in your indexed protocols."

    # off-topic
    r = docs.ask("What is the recommended centrifuge speed for pelleting E. coli?")
    assert r["refused"]
