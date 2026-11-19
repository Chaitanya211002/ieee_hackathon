from backend import nodes
from backend.config import get_config
from backend.pipelines import code
from tests.conftest import needs_ollama


def test_extract_code():
    assert code.extract_code("hi\n```python\nprint(1)\n```\nbye") == "print(1)\n"
    assert code.extract_code("print(2)") == "print(2)\n"


@needs_ollama
def test_generate_with_win_down_falls_back(monkeypatch, tmp_path):
    monkeypatch.setitem(get_config()["nodes"], "win", {"ollama": "http://127.0.0.1:9", "service": "http://127.0.0.1:9"})
    nodes._status.clear()
    r = code.generate(
        "Read d.csv, print the mean of column y, and save a line plot of y against x as plot.png",
        files={"d.csv": b"x,y\n1,2\n2,4\n3,6\n"},
        out_dir=tmp_path,
    )
    assert r["ok"] and r["executed"]
    assert r["coder_node"] == "M5" and r["sandbox_node"] == "M5"
    assert "4" in r["stdout"]
    assert any(p.endswith(".png") for p in r["plots"])


def test_node_down_is_logged(monkeypatch):
    import json

    from backend.config import path

    monkeypatch.setitem(get_config()["nodes"], "win", {"ollama": "http://127.0.0.1:9", "service": "http://127.0.0.1:9"})
    nodes._status.clear()
    nodes.refresh("win")
    rows = [json.loads(x) for x in (path("logs") / "events.jsonl").read_text().splitlines()]
    assert {r["node"] for r in rows if r["event"] == "node_down"} == {"win.ollama", "win.service"}
    nodes.refresh("win")  # no change -> nothing new logged
    assert len((path("logs") / "events.jsonl").read_text().splitlines()) == len(rows)
