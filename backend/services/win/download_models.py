"""Run ONCE while online (setup.bat does). Downloads Whisper and the AST sound classifier
into backend/services/win/models so the WIN node never needs the internet at runtime.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

WIN_DIR = Path(__file__).resolve().parent
MODELS_DIR = Path(os.environ.get("WIN_MODELS_DIR", WIN_DIR / "models"))
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "hf"))
os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"
sys.path.insert(0, str(WIN_DIR.parents[2]))  # repo root

from backend.config import get_config  # noqa: E402


def main() -> None:
    from faster_whisper import download_model
    from huggingface_hub import snapshot_download

    models = get_config()["models"]
    whisper = os.environ.get("WHISPER_MODEL", models.get("whisper_win", "large-v3-turbo"))
    sound = os.environ.get("SOUND_MODEL", models["sound"])

    print(f"Downloading Whisper {whisper} ...", flush=True)
    print("  ->", download_model(whisper, cache_dir=str(MODELS_DIR / "whisper")), flush=True)

    print(f"Downloading {sound} ...", flush=True)
    # Only the safetensors weights: the repo also carries a duplicate .bin file.
    path = snapshot_download(
        sound, allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors"]
    )
    print("  ->", path, flush=True)
    print("Models ready.")


if __name__ == "__main__":
    main()
