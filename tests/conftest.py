import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PACK = ROOT / "data" / "practice-pack"


def _ollama_up() -> bool:
    try:
        return httpx.get("http://localhost:11434/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


needs_ollama = pytest.mark.skipif(not _ollama_up(), reason="Ollama is not running on the M5")
needs_pack = pytest.mark.skipif(not PACK.exists(), reason="practice pack not found at data/practice-pack")


@pytest.fixture(autouse=True)
def _isolated_event_log(tmp_path, monkeypatch):
    """Tests must never write into the real data/logs/events.jsonl."""
    from backend.config import get_config

    monkeypatch.setitem(get_config()["paths"], "logs", str(tmp_path / "logs"))
