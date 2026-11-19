import sys

import pytest

from backend.sandbox import local


def test_stdout_and_isolation():
    r = local.run_code("print(6 * 7)")
    assert r["exit_code"] == 0 and r["stdout"].strip() == "42"
    assert r["isolation"]["separate_venv"]


def test_traceback_returned():
    r = local.run_code("x = 1 / 0")
    assert r["exit_code"] == 1 and "ZeroDivisionError" in r["stderr"]


def test_csv_in_png_out():
    code = (
        "import pandas as pd, matplotlib.pyplot as plt\n"
        "df = pd.read_csv('d.csv'); print(df.y.sum())\n"
        "plt.plot(df.x, df.y); plt.savefig('p.png')\n"
    )
    r = local.run_code(code, {"d.csv": b"x,y\n1,2\n2,5\n"})
    assert r["exit_code"] == 0 and r["stdout"].strip() == "7"
    assert r["artifacts"]["p.png"][:8] == b"\x89PNG\r\n\x1a\n"


def test_no_network():
    r = local.run_code("import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)")
    assert r["exit_code"] != 0


@pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS only")
def test_raw_socket_blocked_by_os():
    # Bypass the Python guard; the OS-level profile must still stop it.
    code = "import _socket\ns = _socket.socket(); s.settimeout(3)\ns.connect(('1.1.1.1', 80)); print('CONNECTED')\n"
    r = local.run_code(code)
    assert "CONNECTED" not in r["stdout"] and r["exit_code"] != 0


def test_timeout():
    r = local.run_code("while True:\n    pass", timeout_s=2)
    assert r["exit_code"] == -1 and "Timed out after 2 s" in r["stderr"]


def test_bad_filename():
    with pytest.raises(ValueError):
        local.run_code("print(1)", {"../x.txt": b"x"})
