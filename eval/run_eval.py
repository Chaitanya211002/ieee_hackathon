"""Run the practice pack through the real BenchLog pipelines and write eval/results.md.

    .venv/bin/python eval/run_eval.py --pack data/practice-pack --out eval/results.md
    .venv/bin/python eval/run_eval.py --only text,code --limit 5      # quick partial run

items.json / answers.json are read from --meta (default: paths.practice_meta in config.yaml).
Per-item outputs (which include reference answers) go to eval/raw/, which is gitignored:
the pack's license forbids committing its answers. results.md holds only metrics and item ids.

Metrics
  image  counting accuracy (first number in the answer == reference count) and
         identification accuracy (lenient: >= half the reference's content words in the answer)
  audio  WER on "Transcribe this audio" items, speech-QA accuracy (lenient), sound-label
         accuracy (the answer names the sound; synonyms below)
  text   accuracy on answerable questions (lenient), correct-refusal rate on unanswerable ones,
         false-refusal rate on answerable ones
  code   unit-test pass rate (generated code + the pack's hidden test, run in the M5 sandbox)
  video  question accuracy, scored from each item's generator params
  all    mean latency per modality and per serving node
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import get_config, path  # noqa: E402

STOP = set(
    "a an the of to in on at for and or is are was were be it its this that these those there here with by from "
    "as what which who whom how why when where does do did i you he she they we his her their my our your".split()
)
SOUND_SYNONYMS = {
    "chainsaw": ["chainsaw", "chain saw", "saw"],
    "clock ticking": ["tick", "clock"],
    "crackling fire": ["fire", "crackl"],
    "baby crying": ["baby", "infant", "cry", "crying"],
    "dog barking": ["dog", "bark"],
    "helicopter": ["helicopter"],
    "rain": ["rain"],
    "rooster crowing": ["rooster", "crow", "cock", "chicken"],
    "ocean waves": ["ocean", "wave", "surf", "sea"],
    "sneezing": ["sneez"],
}
COLORS = ["red", "blue", "green", "yellow", "orange", "purple", "black", "white", "pink", "gray", "grey", "brown"]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------
def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", (text or "").lower()).split()


def content_words(text: str) -> list[str]:
    return [w for w in words(text) if w not in STOP]


def lenient_match(answer: str, reference: str) -> bool:
    ref = content_words(reference)
    if not ref:
        return False
    have = set(content_words(answer))
    hit = sum(1 for w in ref if w in have or w.rstrip("s") in have or w + "s" in have)
    return hit / len(ref) >= 0.5


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def first_int(text: str) -> int | None:
    from backend.pipelines.vision import first_int as fi

    return fi(text or "")


def first_mention(text: str, options: list[str]) -> str | None:
    t = (text or "").lower()
    found = [(t.find(o.lower()), o) for o in options if o.lower() in t]
    return min(found)[1] if found else None


def score_video(answer: str, params: dict, reference: str) -> bool:
    a = (answer or "").lower()
    tpl = (params.get("template") or [0])[0]
    if tpl == 1:
        return first_int(a) == params["count"]
    if tpl == 2:
        dirs = ["right", "left", "up", "down"]
        return first_mention(a, dirs) == params["direction"]
    if tpl == 3:
        cs = params["colors"]
        return cs[0] in a and cs[-1] in a and a.find(cs[0]) < a.rfind(cs[-1]) and first_mention(a, COLORS) == cs[0]
    if tpl == 4:
        w0, w1 = params["words"][0].lower(), params["words"][-1].lower()
        return w0 in a and w1 in a and a.find(w0) < a.rfind(w1)
    if tpl == 5:
        other = "shorter" if params["bar"] == "taller" else "taller"
        return params["bar"] in a and other not in a.split(".")[0]
    if tpl == 6:
        return any(k in a for k in ("toward", "closer", "touch", "meet", "collide", "together", "approach"))
    if tpl == 7:
        return first_int(a) == params["numbers"][-1]
    if tpl == 8:
        return first_int(a) == params["appear"] - params["disappear"]
    if tpl == 9:
        return first_int(a) == params["bounces"]
    if tpl == 10:
        return first_mention(a, COLORS) == params["colors"][-1]
    return lenient_match(answer, reference)


def sound_correct(answer: str, reference: str) -> bool:
    key = " ".join(words(reference))
    syns = SOUND_SYNONYMS.get(key, content_words(reference))
    a = (answer or "").lower()
    return any(s in a for s in syns)


# ---------------------------------------------------------------------------
# Per-modality runners
# ---------------------------------------------------------------------------
def run_image(item, ans, pack):
    from backend.pipelines import vision

    r = vision.analyze(pack / item["file"], item["question"])
    is_count = bool(re.match(r"\s*how many", item["question"], re.I))
    if is_count:
        ok = r.get("vlm_count_estimate") == first_int(ans["reference_answer"])
        metric = "count"
    else:
        ok = lenient_match(r["answer"], ans["reference_answer"])
        metric = "identify"
    return {"metric": metric, "ok": ok, "answer": r["answer"], "node": r["node"], "latency_s": r["latency_s"]}


def run_audio(item, ans, pack):
    from backend.pipelines import audio

    r = audio.analyze(pack / item["file"], item["question"])
    src = (ans.get("source_ids") or {}).get("dataset")
    out = {"answer": r.get("answer"), "transcript": r["transcript"], "labels": r["sound_labels"],
           "node": r["transcribe_node"], "latency_s": r["latency_s"]}  # fmt: skip
    if src == "esc10":
        out.update(metric="sound", ok=sound_correct(r.get("answer", ""), ans["reference_answer"]))
        out["top3_hit"] = sound_correct(" ".join(lab["label"] for lab in r["sound_labels"]), ans["reference_answer"])
    elif re.match(r"\s*transcribe", item["question"], re.I):
        out.update(metric="wer", wer=round(wer(ans.get("transcript") or ans["reference_answer"], r["transcript"]), 4))
        out["ok"] = out["wer"] <= 0.1
    else:
        out.update(metric="speech_qa", ok=lenient_match(r.get("answer", ""), ans["reference_answer"]))
        out["wer"] = round(wer(ans["transcript"], r["transcript"]), 4) if ans.get("transcript") else None
    return out


_ingested: set[str] = set()


def run_text(item, ans, pack):
    from backend.pipelines import docs

    pdf = (pack / item["file"]).with_suffix(".pdf")
    doc = pdf if pdf.exists() else pack / item["file"]
    if doc.name not in _ingested:
        docs.ingest(doc)
        _ingested.add(doc.name)
    r = docs.ask(item["question"], source=doc.name)
    answerable = ans.get("answerable", True)
    if answerable:
        ok = (not r["refused"]) and lenient_match(r["answer"], ans["reference_answer"])
    else:
        ok = r["refused"]
    return {"metric": "answerable" if answerable else "unanswerable", "ok": ok, "refused": r["refused"],
            "answer": r["answer"], "reason": r.get("reason"), "citation": r.get("citation"),
            "best_similarity": r["best_similarity"], "node": r["node"], "latency_s": r["latency_s"]}  # fmt: skip


def run_code(item, ans, pack):
    from backend.pipelines import code
    from backend.sandbox import local

    r = code.generate(item["question"])
    test = (pack / "code" / "tests" / f"{item['id']}_test.py").read_text()
    t = local.run_code(r["code"] + "\n\n" + test)
    return {"metric": "unit_tests", "ok": t["exit_code"] == 0, "generated_ran": r["ok"], "attempts": len(r["attempts"]),
            "test_stderr": t["stderr"][-400:], "code": r["code"], "node": r["coder_node"],
            "latency_s": r["latency_s"]}  # fmt: skip


def run_video(item, ans, pack):
    from backend.pipelines import video

    r = video.analyze(pack / item["file"], item["question"])
    ok = score_video(r["answer"], ans.get("params") or {}, ans["reference_answer"])
    return {"metric": "video_qa", "ok": ok, "answer": r["answer"], "node": r["node"], "latency_s": r["latency_s"]}


RUNNERS = {"image": run_image, "audio": run_audio, "text": run_text, "code": run_code, "video": run_video}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def pct(xs) -> str:
    xs = list(xs)
    return f"{100 * sum(xs) / len(xs):.0f}% ({sum(xs)}/{len(xs)})" if xs else "–"


def write_report(rows: list[dict], out: Path, started: float) -> None:
    by = defaultdict(list)
    for r in rows:
        by[r["modality"]].append(r)

    def m(mod, metric):
        return [r for r in by[mod] if r.get("metric") == metric and "error" not in r]

    metrics = []
    if by["image"]:
        metrics += [("Image", "Counting accuracy", pct(r["ok"] for r in m("image", "count"))),
                    ("Image", "Identification accuracy (lenient)", pct(r["ok"] for r in m("image", "identify")))]  # fmt: skip
    if by["audio"]:
        w = [r["wer"] for r in m("audio", "wer")]
        metrics += [
            ("Audio", "Mean WER, transcription items", f"{100 * statistics.mean(w):.1f}% ({len(w)} clips)" if w else "–"),
            ("Audio", "Speech Q&A accuracy (lenient)", pct(r["ok"] for r in m("audio", "speech_qa"))),
            ("Audio", "Sound identification accuracy (answer)", pct(r["ok"] for r in m("audio", "sound"))),
            ("Audio", "Sound in AST top-3 labels", pct(r["top3_hit"] for r in m("audio", "sound"))),
        ]
    if by["text"]:
        ans_rows = m("text", "answerable")
        metrics += [
            ("Text", "Accuracy, answerable (lenient)", pct(r["ok"] for r in ans_rows)),
            ("Text", "Correct refusal, unanswerable", pct(r["ok"] for r in m("text", "unanswerable"))),
            ("Text", "False refusal, answerable", pct(r["refused"] for r in ans_rows)),
        ]
    if by["code"]:
        metrics += [("Code", "Hidden unit tests passed", pct(r["ok"] for r in m("code", "unit_tests"))),
                    ("Code", "Generated code ran without error", pct(r["generated_ran"] for r in m("code", "unit_tests")))]  # fmt: skip
    if by["video"]:
        metrics += [("Video", "Question accuracy", pct(r["ok"] for r in m("video", "video_qa")))]
    errors = [r for r in rows if "error" in r]

    lat = defaultdict(list)
    for r in rows:
        if "latency_s" in r:
            lat[(r["modality"], r.get("node", "?"))].append(r["latency_s"])

    cfg = get_config()
    lines = [
        "# BenchLog eval: practice pack",
        "",
        f"Run {datetime.now().astimezone().isoformat(timespec='minutes')} · {len(rows)} items · "
        f"{(time.time() - started) / 60:.0f} min total · all inference local",
        "",
        f"Models: vision/text `{cfg['models']['vision']}`, coder `{cfg['models']['coder']}`, embeddings "
        f"`{cfg['models']['embed']}`, speech Whisper large-v3-turbo, sounds AST AudioSet. Video: "
        f"{cfg['video']['max_frames']} frames, mode `{cfg['video'].get('mode', 'frames')}`.",
        "",
        "| Modality | Metric | Result |",
        "|---|---|---|",
        *[f"| {a} | {b} | {c} |" for a, b, c in metrics],
        "",
        "## Latency",
        "",
        "| Modality | Node | Items | Mean (s) | Max (s) |",
        "|---|---|---|---|---|",
        *[
            f"| {mod} | {node} | {len(v)} | {statistics.mean(v):.1f} | {max(v):.1f} |"
            for (mod, node), v in sorted(lat.items())
        ],
        "",
        "## Per item (pass/fail only; answers stay out of the repo per the pack license)",
        "",
        "| Modality | Pass | Fail |",
        "|---|---|---|",
    ]
    for mod in ("image", "audio", "text", "code", "video"):
        if by[mod]:
            ok = [r["id"] for r in by[mod] if r.get("ok")]
            bad = [r["id"] + (" (error)" if "error" in r else "") for r in by[mod] if not r.get("ok")]
            lines.append(f"| {mod} | {', '.join(ok) or '–'} | {', '.join(bad) or '–'} |")
    lines += [
        "",
        "Scoring notes: lenient = at least half the reference answer's content words appear in the model's "
        "answer. Image counts compare the first number in the VLM answer (a VLM estimate; plates also get an "
        "OpenCV count). WER is word error rate against the reference transcript. Code items count as passed "
        "only if the pack's unit tests pass on the generated code. Video answers are scored against each "
        "clip's generator parameters (count, direction, colour order, words).",
    ]
    if errors:
        lines += ["", f"Errors: {len(errors)} item(s) raised; see eval/raw/ for tracebacks."]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=str(path("practice_pack")))
    ap.add_argument("--meta", default=str(path("practice_meta")), help="folder with items.json and answers.json")
    ap.add_argument("--out", default=str(ROOT / "eval" / "results.md"))
    ap.add_argument("--only", help="comma-separated modalities")
    ap.add_argument("--limit", type=int, help="max items per modality")
    a = ap.parse_args()

    pack, meta = Path(a.pack), Path(a.meta)
    if not (meta / "items.json").exists() and (pack / "items.json").exists():
        meta = pack
    items = json.loads((meta / "items.json").read_text())
    answers = {x["id"]: x for x in json.loads((meta / "answers.json").read_text())}
    only = set(a.only.split(",")) if a.only else set(RUNNERS)

    # Separate index so the eval never touches the lab's real protocol index.
    get_config()["paths"]["chroma"] = str(ROOT / "data" / "eval_chroma")
    import shutil

    shutil.rmtree(ROOT / "data" / "eval_chroma", ignore_errors=True)

    raw_dir = ROOT / "eval" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw = (raw_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl").open("w")
    rows, counts, started = [], defaultdict(int), time.time()
    for item in items:
        mod = item["modality"]
        if mod not in only or (a.limit and counts[mod] >= a.limit):
            continue
        counts[mod] += 1
        t0 = time.time()
        try:
            r = RUNNERS[mod](item, answers[item["id"]], pack)
        except Exception as exc:  # noqa: BLE001 - record and keep going
            r = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]}
        r.update(id=item["id"], modality=mod, wall_s=round(time.time() - t0, 2))
        rows.append(r)
        raw.write(json.dumps({**r, "question": item["question"], "reference": answers[item["id"]]["reference_answer"]},
                             default=str) + "\n")  # fmt: skip
        raw.flush()
        print(f"{'PASS' if r.get('ok') else 'FAIL'} {item['id']:<11} {r.get('metric', ''):<12} "
              f"{r.get('node', '')} {r.get('latency_s', '')}s {r.get('error', '')}", flush=True)  # fmt: skip
    raw.close()
    write_report(rows, Path(a.out), started)
    print(f"\nWrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
