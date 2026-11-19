"""M5 fallback code executor. Same request/response shape as the WIN node's POST /run_code.

run_code(code, files) writes `files` into a fresh temp dir, writes `code` to main.py and runs
it with the sandbox venv's Python (separate from the app's venv), cwd = temp dir, a timeout,
a minimal environment and no network. Every *.png left in the temp dir is returned.

No network, best effort, in three layers:
  1. macOS: the process runs under `sandbox-exec` with a profile that denies all network.
  2. A .pth guard in the sandbox venv replaces socket connect/getaddrinfo (backend/sandbox/guard.py).
  3. Proxy variables point at a dead port, and nothing else from our environment is inherited.
This stops ordinary networking from generated analysis code. It is not a hardened boundary
against deliberately hostile code (no filesystem jail beyond the temp cwd); see README.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from backend.config import REPO_ROOT, get_config

log = logging.getLogger("benchlog.sandbox")

MAX_OUTPUT_CHARS = 200_000
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
DENY_NETWORK_PROFILE = "(version 1)(allow default)(deny network*)"


def sandbox_python() -> tuple[Path, bool]:
    """(python executable, is_isolated_venv). Falls back to this interpreter if the venv is missing."""
    p = Path(get_config()["sandbox"]["local_python"])
    p = p if p.is_absolute() else REPO_ROOT / p
    if p.exists():
        return p, True
    log.warning("sandbox venv %s missing (run scripts/setup_sandbox.sh); using %s", p, sys.executable)
    return Path(sys.executable), False


def _env(tmp: Path, py: Path) -> dict[str, str]:
    dead = "http://127.0.0.1:9"
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp),
        "TMPDIR": str(tmp),
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(py.parent.parent / ".mplconfig"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "BENCHLOG_SANDBOX": "1",
        "HTTP_PROXY": dead,
        "HTTPS_PROXY": dead,
        "http_proxy": dead,
        "https_proxy": dead,
        "NO_PROXY": "",
    }


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n... [truncated, {len(text) - MAX_OUTPUT_CHARS} more chars]"


def run_code(code: str, files: dict[str, bytes] | None = None, timeout_s: int | None = None) -> dict[str, Any]:
    """Execute `code`. Returns {"stdout", "stderr", "exit_code", "artifacts": {name: bytes}, ...}.

    exit_code -1 means it timed out ("Timed out after N s" is appended to stderr).
    """
    cfg = get_config()["sandbox"]
    timeout_s = timeout_s or int(cfg["timeout_s"])
    py, isolated = sandbox_python()
    for name in files or {}:
        if Path(name).name != name or name in ("", ".", "..", "main.py"):
            raise ValueError(f"invalid file name: {name!r}")

    cmd = [str(py), "-I", "-X", "utf8", "main.py"]
    os_block = bool(cfg.get("os_network_block")) and sys.platform == "darwin" and shutil.which("sandbox-exec")
    if os_block:
        cmd = ["sandbox-exec", "-p", DENY_NETWORK_PROFILE, *cmd]

    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="benchlog_run_") as tmp_name:
        tmp = Path(tmp_name)
        for name, data in (files or {}).items():
            (tmp / name).write_bytes(data)
        (tmp / "main.py").write_text(code, encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=tmp,
            env=_env(tmp, py),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout_s)
            exit_code = proc.returncode
            stderr = err.decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            out, err = proc.communicate()
            exit_code = -1
            partial = err.decode("utf-8", "replace").rstrip()
            stderr = (partial + "\n" if partial else "") + f"Timed out after {timeout_s} s"

        artifacts: dict[str, bytes] = {}
        total = 0
        for png in sorted(tmp.glob("*.png")):
            total += png.stat().st_size
            if total > MAX_ARTIFACT_BYTES:
                stderr += f"\n[artifact {png.name} dropped: over the size limit]"
                continue
            artifacts[png.name] = png.read_bytes()

    seconds = round(time.time() - t0, 2)
    log.info("sandbox.local node=M5 exit_code=%s artifacts=%d latency=%.2fs", exit_code, len(artifacts), seconds)
    return {
        "stdout": _clip(out.decode("utf-8", "replace")),
        "stderr": _clip(stderr),
        "exit_code": exit_code,
        "artifacts": artifacts,
        "node": "M5",
        "seconds": seconds,
        "isolation": {"separate_venv": isolated, "os_network_block": bool(os_block)},
    }
