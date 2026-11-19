"""Network block for code run by /run_code.

setup.bat copies this file into sandbox_venv's site-packages as benchlog_sandbox_guard.py
and adds a one-line benchlog_sandbox.pth that imports it, so Python loads it before any
sandboxed script starts. (A .pth file is used instead of sitecustomize.py because a
sitecustomize.py elsewhere on the path would silently take its place.)

It only activates when the WIN service launched the process (BENCHLOG_SANDBOX=1), which
keeps `pip install` inside sandbox_venv working.

This stops ordinary Python networking (requests, urllib, sockets). It is not a security
boundary against deliberately hostile code; see the README.
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
