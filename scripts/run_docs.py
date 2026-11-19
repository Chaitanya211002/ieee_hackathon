"""Index protocols and ask questions.

    .venv/bin/python scripts/run_docs.py ingest data/practice-pack/text/p_txt_doc_01.pdf
    .venv/bin/python scripts/run_docs.py ask "Who defeated Montcalm at Quebec?" [--source p_txt_doc_01.pdf]
    .venv/bin/python scripts/run_docs.py list
"""

import argparse

from _common import show

from backend.pipelines import docs

p = argparse.ArgumentParser()
sub = p.add_subparsers(dest="cmd", required=True)
sub.add_parser("ingest").add_argument("file")
q = sub.add_parser("ask")
q.add_argument("question")
q.add_argument("--source")
sub.add_parser("list")
a = p.parse_args()
if a.cmd == "ingest":
    show(docs.ingest(a.file))
elif a.cmd == "ask":
    r = docs.ask(a.question, a.source)
    for h in r.get("retrieved", []):
        h["text"] = h["text"][:120] + "…"
    show(r)
else:
    show({"protocols": docs.list_protocols()})
