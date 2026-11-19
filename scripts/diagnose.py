"""One-screen summary of what BenchLog has been doing, from data/logs/events.jsonl.

    .venv/bin/python scripts/diagnose.py              # last 24 h
    .venv/bin/python scripts/diagnose.py --hours 2    # a shorter window
    .venv/bin/python scripts/diagnose.py --all        # include every captured entry, not just problems

Shows: server starts and their mode, node up/down changes, failed and rejected captures (with
the end of the traceback), fallbacks from WIN to the M5, browser-side errors, latency per
entry type, and the result of a live /status and /verify if the server is running.
Full tracebacks are in data/logs/api.log.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "logs" / "events.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--url", default="http://localhost:8000")
    a = ap.parse_args()

    rows = []
    if EVENTS.exists():
        since = datetime.now().astimezone() - timedelta(hours=a.hours)
        for line in EVENTS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if datetime.fromisoformat(r["ts"]) >= since:
                    rows.append(r)
            except (ValueError, KeyError):
                continue
    print(f"Events in the last {a.hours:g} h: {len(rows)}  ({EVENTS.relative_to(ROOT)})\n")

    def t(r):
        return r["ts"][11:19]

    starts = [r for r in rows if r["event"] == "server_start"]
    if starts:
        print("Server starts:")
        for r in starts[-5:]:
            mode = "two laptops" if "WIN_IP" not in str(r.get("win_service")) else "single laptop"
            print(f"  {t(r)}  {mode:<13} config={r.get('config')}  win={r.get('win_service')}")
        print()

    changes = [r for r in rows if r["event"] in ("node_up", "node_down")]
    if changes:
        print("Node changes:")
        for r in changes[-15:]:
            print(f"  {t(r)}  {r['node']:<12} {r['event'][5:]:<5} {r.get('error') or ''}"[:160])
        print()

    problems = [r for r in rows if r["event"] in ("entry_error", "entry_rejected", "client_error")]
    print(f"Problems: {len(problems)}")
    for r in problems[-20:]:
        what = r.get("file") or r.get("text") or r.get("where") or ""
        print(f"  {t(r)}  {r['event']:<14} {str(what)[:50]!r}: {str(r.get('error') or r.get('message'))[:120]}")
        if r.get("traceback"):
            tail = [ln for ln in r["traceback"].splitlines() if ln.strip()][-3:]
            for ln in tail:
                print(f"      {ln.strip()[:150]}")
    print()

    entries = [r for r in rows if r["event"] == "entry"]
    fb = [(r, f) for r in entries for f in r.get("fallbacks") or []]
    print(f"Captures: {len(entries)}   with a WIN->M5 fallback: {len({id(r) for r, _ in fb})}")
    for r, f in fb[-10:]:
        print(f"  {t(r)}  {r['type']:<11} {f['where']}: from {f['from']} ({f['error'][:90]})")
    failed_code = [r for r in entries if r["type"] == "analysis" and r.get("ok") is False]
    for r in failed_code[-5:]:
        print(f"  {t(r)}  code did not run: {r['summary'][:110]}")

    by = defaultdict(list)
    for r in entries:
        by[(r["type"], r.get("node"))].append(r.get("seconds") or 0)
    if by:
        print("\nLatency by entry type (s):")
        for (typ, node), v in sorted(by.items()):
            print(f"  {typ:<12} {node:<4} n={len(v):<3} mean={statistics.mean(v):6.1f}  max={max(v):6.1f}")
    if a.all:
        print("\nAll captures:")
        for r in entries:
            print(f"  {t(r)}  {r['type']:<11} {r.get('node'):<4} {r.get('seconds')}s  {r['summary'][:90]}")

    print("\nLive:")
    try:
        s = httpx.get(f"{a.url}/status", timeout=3).json()
        print("  jobs:  " + ", ".join(f"{j}->{v['serving']}" for j, v in s["jobs"].items()))
        down = [k for k, v in s["nodes"].items() if not v["up"] and v.get("error") != "not configured"]
        print("  down:  " + (", ".join(f"{k} ({s['nodes'][k].get('error')})" for k in down) or "none"))
        v = httpx.get(f"{a.url}/verify", timeout=5).json()
        print(f"  chain: {'verified' if v['ok'] else 'BROKEN at ' + str(v['first_broken'])}, {v['entries']} entries")
    except Exception as exc:  # noqa: BLE001
        print(f"  server not reachable at {a.url}: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
