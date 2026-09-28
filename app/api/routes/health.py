"""Health check routes."""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_db

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Basic liveness check."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(db: Any = Depends(get_db)) -> dict[str, str]:
    """Readiness check including database connectivity."""
    await db.command("ping")
    return {"status": "ready"}
