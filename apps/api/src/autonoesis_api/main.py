"""API process assembly."""

from typing import Any

from fastapi import FastAPI

app = FastAPI(
    title="Autonoesis API",
    description="Enterprise Governed Self-Evolving Agent Operating System",
    version="0.1.0",
)


@app.get("/health/live", tags=["health"])
async def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "autonoesis-api"}


@app.get("/", tags=["system"])
async def root() -> dict[str, Any]:
    return {
        "name": "Autonoesis",
        "category": "Enterprise Governed Self-Evolving Agent Operating System",
        "phase": "architecture-baseline",
    }
