"""Config loader. Everything tunable comes from backend/config.yaml."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("BENCHLOG_CONFIG", REPO_ROOT / "backend" / "config.yaml"))

# Never download model weights at runtime. Run scripts/prefetch_models.py once while online.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")  # chromadb telemetry off


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def path(key: str) -> Path:
    """Resolve a paths.<key> entry relative to the repo root."""
    p = Path(get_config()["paths"][key])
    return p if p.is_absolute() else REPO_ROOT / p
