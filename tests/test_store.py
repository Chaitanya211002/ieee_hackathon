import json
import sqlite3

import pytest

from backend.store import GENESIS, Store, compute_hash


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.sqlite3", tmp_path / "media")


def _fill(store, n=4):
    return [
        store.add_entry(type="note", summary=f"entry {i}", details={"i": i, "nested": {"b": 2, "a": 1}})
        for i in range(n)
    ]


def test_genesis_and_links(store):
    es = _fill(store)
    assert es[0]["prev_hash"] == GENESIS
    for a, b in zip(es, es[1:]):
        assert b["prev_hash"] == a["hash"]
    assert all(len(e["hash"]) == 64 for e in es)


def test_contract_shape(store):
    e = store.add_entry(type="photo", summary="plate", artifacts=[{"kind": "image", "path": "x.jpg"}])
    assert set(e) == {"id", "type", "created_at", "summary", "details", "artifacts", "hash", "prev_hash", "node"}


def test_hash_formula(store):
    e = store.add_entry(type="note", summary="s", details={"k": "v"})
    raw = store.get_entry(e["id"])
    h = raw.pop("hash")
    assert h == compute_hash(raw["prev_hash"], raw)


def test_verify_clean(store):
    _fill(store)
    assert store.verify_chain() is None
    assert store.verify_report()["ok"]


def test_verify_empty(store):
    assert store.verify_chain() is None


def _tamper(store, sql, args):
    c = sqlite3.connect(store.db_path)
    c.execute(sql, args)
    c.commit()
    c.close()


def test_tamper_summary_detected(store):
    es = _fill(store)
    _tamper(store, "UPDATE entries SET summary = ? WHERE id = ?", ("edited!", es[2]["id"]))
    assert store.verify_chain() == es[2]["id"]


def test_tamper_details_detected(store):
    es = _fill(store)
    _tamper(store, "UPDATE entries SET details = ? WHERE id = ?", (json.dumps({"i": 99}), es[1]["id"]))
    assert store.verify_chain() == es[1]["id"]


def test_tamper_rehash_detected_at_next(store):
    """Editing a row AND recomputing its hash still breaks the link to the next entry."""
    es = _fill(store)
    raw = store.get_entry(es[1]["id"])
    raw.pop("hash")
    raw["summary"] = "forged"
    new_hash = compute_hash(raw["prev_hash"], raw)
    _tamper(store, "UPDATE entries SET summary = ?, hash = ? WHERE id = ?", ("forged", new_hash, es[1]["id"]))
    assert store.verify_chain() == es[2]["id"]


def test_delete_detected(store):
    es = _fill(store)
    _tamper(store, "DELETE FROM entries WHERE id = ?", (es[1]["id"],))
    assert store.verify_chain() == es[2]["id"]


def test_list_filters(store):
    store.ensure_experiment("expA", "A")
    store.add_entry(type="note", summary="a", experiment_id="expA")
    store.add_entry(type="note", summary="b")
    assert [e["summary"] for e in store.list_entries("expA")] == ["a"]
    today = store.list_entries()[0]["created_at"][:10]
    assert len(store.list_entries(date=today)) == 2
    assert store.list_entries(date="1999-01-01") == []


def test_bad_type_rejected(store):
    with pytest.raises(ValueError):
        store.add_entry(type="banana", summary="x")


def test_save_media(store, tmp_path):
    src = tmp_path / "plate 1.jpg"
    src.write_bytes(b"jpeg")
    rel = store.save_media(src, src.name)
    assert (store.media_dir / rel).read_bytes() == b"jpeg"
    assert " " not in rel
