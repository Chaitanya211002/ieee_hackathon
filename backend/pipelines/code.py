"""Code pipeline: Qwen2.5-Coder writes Python, the sandbox runs it, errors are fed back.

generate(prompt, files=...) -> {"code", "stdout", "stderr", "exit_code", "ok", "executed",
"plots", "attempts", ...}. The coder model runs on the `coder` node (WIN, fallback M5) and the
code runs on the `sandbox` node (WIN /run_code, fallback backend/sandbox/local.py). Code is only
reported as working (ok=True) after it actually ran with exit code 0.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from backend import nodes
from backend.config import get_config
from backend.sandbox import local as local_sandbox

log = logging.getLogger("benchlog.code")

SYSTEM_PROMPT = (
    "You are the analysis assistant in BenchLog, a lab notebook. Write one complete, runnable "
    "Python 3 script that does what the user asks. Rules:\n"
    "- Reply with a single ```python code block and nothing else.\n"
    "- Use only the standard library, numpy, pandas and matplotlib. There is no network access.\n"
    "- Input files, if any, are in the current directory; open them by the names given.\n"
    "- Print the key results to stdout so they appear in the notebook.\n"
    "- For plots use matplotlib, save them with plt.savefig('<name>.png') in the current "
    "directory, and never call plt.show().\n"
    "- If asked to complete or write a function, write the full function with any imports it "
    "needs, then print the result of two or three example calls. Do not write assert statements."
)

CODE_BLOCK = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def extract_code(text: str) -> str:
    blocks = CODE_BLOCK.findall(text)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    return text.strip().strip("`").strip() + "\n"


def describe_files(files: dict[str, bytes]) -> str:
    """Tell the model what the input files look like (CSV columns and first rows)."""
    lines = []
    for name, data in files.items():
        if name.lower().endswith((".csv", ".tsv")):
            try:
                import pandas as pd

                df = pd.read_csv(io.BytesIO(data), sep="\t" if name.lower().endswith(".tsv") else ",")
                lines.append(
                    f"- {name}: {len(df)} rows; columns {list(df.columns)}; first rows:\n"
                    f"{df.head(3).to_csv(index=False)}"
                )
                continue
            except Exception:  # noqa: BLE001 - fall through to a plain mention
                pass
        lines.append(f"- {name} ({len(data)} bytes)")
    return "Input files in the current directory:\n" + "\n".join(lines)


def _ask_coder(messages: list[dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    model = get_config()["models"]["coder"]
    return nodes.run_job(
        "coder",
        remote=lambda node: nodes.chat(node, model, messages),
        local=lambda: nodes.chat("m5", model, messages),
    )


def _win_run_code(node: str, code: str, files: dict[str, bytes]) -> dict[str, Any]:
    url = nodes.node_url(node, "service")
    payload = {"code": code, "files": {k: base64.b64encode(v).decode() for k, v in files.items()}}
    r = httpx.post(f"{url}/run_code", json=payload, timeout=get_config()["timeouts"]["win_service_s"])
    r.raise_for_status()
    res = r.json()
    res["artifacts"] = {k: base64.b64decode(v) for k, v in res.get("artifacts", {}).items()}
    return res


def execute(code: str, files: dict[str, bytes] | None = None) -> tuple[dict[str, Any], str, dict[str, Any]]:
    files = files or {}
    return nodes.run_job(
        "sandbox",
        remote=lambda node: _win_run_code(node, code, files),
        local=lambda: local_sandbox.run_code(code, files),
    )


def generate(
    prompt: str,
    files: dict[str, bytes] | None = None,
    csv_columns: list[str] | None = None,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Write code for `prompt`, run it, retry with the traceback up to sandbox.max_retries times."""
    t0 = time.time()
    files = files or {}
    max_retries = int(get_config()["sandbox"]["max_retries"])
    user = prompt.strip()
    if files:
        user += "\n\n" + describe_files(files)
    elif csv_columns:
        user += f"\n\nThe data has columns: {csv_columns}"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]

    attempts: list[dict[str, Any]] = []
    code, run, coder_node, sandbox_node = "", {}, "M5", "M5"
    for attempt in range(max_retries + 1):
        reply, coder_node, coder_meta = _ask_coder(messages)
        code = extract_code(reply)
        run, sandbox_node, sandbox_meta = execute(code, files)
        attempts.append(
            {
                "attempt": attempt + 1,
                "exit_code": run["exit_code"],
                "coder_node": coder_node,
                "sandbox_node": sandbox_node,
                "coder_latency_s": coder_meta.get("latency_s"),
                "sandbox_latency_s": sandbox_meta.get("latency_s"),
                **({"stderr_tail": run["stderr"][-600:]} if run["exit_code"] != 0 else {}),
                **{k: v for k, v in {**coder_meta, **sandbox_meta}.items() if k.startswith("fallback")},
            }
        )
        if run["exit_code"] == 0:
            break
        messages += [
            {"role": "assistant", "content": f"```python\n{code}```"},
            {
                "role": "user",
                "content": "Running that script failed with this error:\n"
                f"```\n{run['stderr'][-3000:]}\n```\nFix it and reply with the complete corrected script.",
            },
        ]

    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="benchlog_code_"))
    out.mkdir(parents=True, exist_ok=True)
    plots = []
    for name, data in run.get("artifacts", {}).items():
        (out / name).write_bytes(data)
        plots.append(str(out / name))

    ok = run.get("exit_code") == 0
    latency = round(time.time() - t0, 2)
    log.info("code.generate coder=%s sandbox=%s ok=%s attempts=%d latency=%.2fs",
             coder_node, sandbox_node, ok, len(attempts), latency)  # fmt: skip
    return {
        "prompt": prompt,
        "code": code,
        "stdout": run.get("stdout", ""),
        "stderr": run.get("stderr", ""),
        "exit_code": run.get("exit_code"),
        "executed": True,
        "ok": ok,
        "plots": plots,
        "attempts": attempts,
        "model": get_config()["models"]["coder"],
        "coder_node": coder_node,
        "sandbox_node": sandbox_node,
        "node": coder_node,
        "latency_s": latency,
    }
