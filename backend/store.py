"""SQLite notebook store with a tamper-evident hash chain.

hash = sha256(prev_hash + canonical_json(entry_without_hash))

`entry_without_hash` is every stored field except `hash`: the API-contract fields (id, type,
created_at, summary, details, artifacts, prev_hash, node) plus `experiment_id`, so moving an
entry to another experiment also breaks the chain. There is one global chain across all
experiments, ordered by insertion (`seq`). The genesis entry's prev_hash is 64 zeros.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

GENESIS = "0" * 64
ENTRY_TYPES = {"voice", "photo", "video", "protocol_qa", "analysis", "note"}
NODES = {"M5", "WIN", "M1"}
DEFAULT_EXPERIMENT = "default"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS entries (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    id            TEXT UNIQUE NOT NULL,
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    type          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    summary       TEXT NOT NULL,
    details       TEXT NOT NULL,   -- JSON object
    artifacts     TEXT NOT NULL,   -- JSON list
    node          TEXT NOT NULL,
    prev_hash     TEXT NOT NULL,
    hash          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS entries_exp ON entries(experiment_id, created_at);
"""

CONTRACT_KEYS = ("id", "type", "created_at", "summary", "details", "artifacts", "hash", "prev_hash", "node")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, entry_without_hash: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(entry_without_hash)).encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: str | Path, media_dir: str | Path):
        self.db_path = Path(db_path)
        self.media_dir = Path(media_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)
        self.ensure_experiment(DEFAULT_EXPERIMENT, "Default experiment")

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        return c

    # ---------- experiments ----------
    def ensure_experiment(self, experiment_id: str, name: str | None = None) -> dict[str, Any]:
        with self._conn() as c:
            c.execute(
                "INSERT OR IGNORE INTO experiments (id, name, created_at) VALUES (?, ?, ?)",
                (experiment_id, name or experiment_id, _now_iso()),
            )
            row = c.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
        return dict(row)

    def create_experiment(self, name: str) -> dict[str, Any]:
        return self.ensure_experiment(uuid.uuid4().hex[:12], name)

    def list_experiments(self) -> list[dict[str, Any]]:
        """Experiments with `entry_count` = entries still shown in the notebook (deleted ones excluded)."""
        gone = self.deleted_ids()
        with self._conn() as c:
            rows = c.execute("SELECT * FROM experiments ORDER BY created_at").fetchall()
            counts: dict[str, int] = {}
            for r in c.execute("SELECT id, experiment_id FROM entries"):
                if r["id"] not in gone:
                    counts[r["experiment_id"]] = counts.get(r["experiment_id"], 0) + 1
        return [{**dict(r), "entry_count": counts.get(r["id"], 0)} for r in rows]

    # ---------- media ----------
    def save_media(self, src: str | Path | bytes, filename: str) -> str:
        """Copy a file (or bytes) into data/media/<date>/ and return the path relative to media_dir."""
        day = datetime.now().strftime("%Y-%m-%d")
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in Path(filename).name) or "file"
        rel = Path(day) / f"{uuid.uuid4().hex[:8]}_{safe}"
        dest = self.media_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(src, bytes):
            dest.write_bytes(src)
        else:
            shutil.copyfile(src, dest)
        return rel.as_posix()

    # ---------- entries ----------
    def add_entry(
        self,
        *,
        type: str,
        summary: str,
        details: dict[str, Any] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        node: str = "M5",
        experiment_id: str = DEFAULT_EXPERIMENT,
    ) -> dict[str, Any]:
        if type not in ENTRY_TYPES:
            raise ValueError(f"unknown entry type {type!r}")
        if node not in NODES:
            raise ValueError(f"unknown node {node!r}")
        self.ensure_experiment(experiment_id)
        entry = {
            "id": str(uuid.uuid4()),
            "experiment_id": experiment_id,
            "type": type,
            "created_at": _now_iso(),
            "summary": summary,
            "details": details or {},
            "artifacts": artifacts or [],
            "node": node,
        }
        # Round-trip through JSON so the hashed form equals what we read back later.
        entry = json.loads(json.dumps(entry, default=str))
        c = self._conn()
        try:
            c.execute("BEGIN IMMEDIATE")  # serialize writers so the chain never forks
            last = c.execute("SELECT hash FROM entries ORDER BY seq DESC LIMIT 1").fetchone()
            entry["prev_hash"] = last["hash"] if last else GENESIS
            entry["hash"] = compute_hash(entry["prev_hash"], entry)
            c.execute(
                "INSERT INTO entries (id, experiment_id, type, created_at, summary, details, artifacts, node, "
                "prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    entry["id"],
                    entry["experiment_id"],
                    entry["type"],
                    entry["created_at"],
                    entry["summary"],
                    canonical_json(entry["details"]),
                    canonical_json(entry["artifacts"]),
                    entry["node"],
                    entry["prev_hash"],
                    entry["hash"],
                ),
            )
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()
        return to_contract(entry)

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d.pop("seq", None)
        d["details"] = json.loads(d["details"])
        d["artifacts"] = json.loads(d["artifacts"])
        return d

    def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return self._row_to_entry(row) if row else None

    def list_entries(
        self, experiment_id: str | None = None, date: str | None = None, include_deleted: bool = False
    ) -> list[dict[str, Any]]:
        """Entries in chain order. `date` is YYYY-MM-DD in the lab's local time.

        Deleted entries are left out unless `include_deleted`; their deletion records are listed.
        """
        sql, args = "SELECT * FROM entries WHERE 1=1", []
        if experiment_id:
            sql += " AND experiment_id = ?"
            args.append(experiment_id)
        if date:
            sql += " AND substr(created_at, 1, 10) = ?"
            args.append(date)
        with self._conn() as c:
            rows = c.execute(sql + " ORDER BY seq", args).fetchall()
        gone = set() if include_deleted else self.deleted_ids()
        return [self._row_to_entry(r) for r in rows if r["id"] not in gone]

    # ---------- deletion ----------
    # Deleting never removes a row: that would break every hash after it, and a notebook that can
    # lose entries silently is not tamper-evident. Instead a deletion is itself a chained entry
    # (a note with details.kind == "deletion") naming what it removed. The listing hides the named
    # entries, the chain still verifies, and the fact that something was deleted stays on record.
    def deleted_ids(self) -> set[str]:
        """Ids of the entries that deletion records have taken out of the notebook."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT details FROM entries WHERE type = 'note' AND details LIKE ?", ('%"kind":"deletion"%',)
            ).fetchall()
        gone: set[str] = set()
        for r in rows:
            d = json.loads(r["details"])
            if d.get("kind") == "deletion":
                gone.update(x["id"] for x in d.get("deleted", []))
        return gone

    def delete_entry(self, entry_id: str) -> dict[str, Any]:
        """Take an entry, and any follow-ups asked about it, out of the notebook.

        Appends a deletion record and returns it (API-contract shape). Raises KeyError when the
        entry does not exist or is already deleted, ValueError for a deletion record itself.
        """
        target = self.get_entry(entry_id)
        if target is None or entry_id in self.deleted_ids():
            raise KeyError(entry_id)
        if target["details"].get("kind") == "deletion":
            raise ValueError("a deletion record cannot be deleted")
        thread = [target] + [
            e for e in self.list_entries(target["experiment_id"]) if e["details"].get("thread_root") == entry_id
        ]
        label = target["type"].replace("_", " ")
        text = f"Deleted a {label} entry from {target['created_at'][11:16]}"
        if len(thread) > 1:
            text += f" and its {len(thread) - 1} follow-up{'s' if len(thread) > 2 else ''}"
        return self.add_entry(
            type="note",
            summary=text,
            details={
                "kind": "deletion",
                "text": text,
                "deleted": [
                    {"id": e["id"], "type": e["type"], "created_at": e["created_at"], "hash": e["hash"]} for e in thread
                ],
            },
            node="M5",
            experiment_id=target["experiment_id"],
        )

    # ---------- verification ----------
    def verify_report(self) -> dict[str, Any]:
        prev = GENESIS
        n = 0
        with self._conn() as c:
            rows = c.execute("SELECT * FROM entries ORDER BY seq").fetchall()
        for row in rows:
            e = self._row_to_entry(row)
            stored = e.pop("hash")
            reason = None
            if e["prev_hash"] != prev:
                reason = "prev_hash does not match previous entry's hash"
            elif compute_hash(prev, e) != stored:
                reason = "content does not match its hash"
            if reason:
                return {"ok": False, "entries": len(rows), "verified": n, "first_broken": e["id"], "reason": reason}
            prev = stored
            n += 1
        return {"ok": True, "entries": len(rows), "verified": n, "first_broken": None, "head": prev}

    def verify_chain(self) -> str | None:
        """Return the id of the first broken entry, or None if the whole chain verifies."""
        return self.verify_report()["first_broken"]


def to_contract(entry: dict[str, Any]) -> dict[str, Any]:
    """Shape an entry exactly as the frozen API contract (experiment_id is not a top-level key)."""
    return {k: entry[k] for k in CONTRACT_KEYS}


_default: Store | None = None


def get_store() -> Store:
    global _default
    if _default is None:
        from backend.config import path

        _default = Store(path("db"), path("media"))
    return _default
