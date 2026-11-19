"""Python-level network block for sandboxed code (same idea as the WIN node's sandbox_guard.py).

scripts/setup_sandbox.sh copies this into the sandbox venv's site-packages and adds a .pth
file that imports it, so it loads before user code. It only activates when BENCHLOG_SANDBOX=1,
which keeps `pip install` inside the sandbox venv working. Best effort, not a security boundary;
on macOS the executor additionally runs the process under sandbox-exec with network denied.
"""

import os

if os.environ.get("BENCHLOG_SANDBOX") == "1":
    import socket

    def _blocked(*_args, **_kwargs):
        raise OSError("Network access is disabled in the BenchLog sandbox")

    socket.socket.connect = _blocked
    socket.socket.connect_ex = _blocked
    socket.socket.sendto = _blocked
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
    socket.gethostbyname = _blocked
