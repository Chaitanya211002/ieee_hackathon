"""Shared setup for the pipeline scripts: repo root on sys.path, logging, JSON printing."""

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


def show(result: dict) -> None:
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
