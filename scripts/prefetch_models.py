"""Run ONCE while online. Downloads the Hugging Face models (Whisper for mlx, AST sound
classifier) into the local HF cache so the app never needs the internet at runtime.

    .venv/bin/python scripts/prefetch_models.py
"""

import os
import sys
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from huggingface_hub import snapshot_download  # noqa: E402  (ships with transformers)

from backend.config import get_config  # noqa: E402

models = get_config()["models"]
for repo in (models["whisper"], models["sound"]):
    print(f"Downloading {repo} ...")
    print("  ->", snapshot_download(repo))
print("Done. Ollama models are pulled separately with `ollama pull`.")
