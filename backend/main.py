"""BenchLog FastAPI orchestrator (skeleton; endpoints arrive in Phase 4)."""

from fastapi import FastAPI

from backend.config import get_config

app = FastAPI(title="BenchLog")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "models": get_config()["models"]}
