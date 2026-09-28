"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import audits, health
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.database.indexes import ensure_indexes_async
from app.database.session import close_async_client


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler."""
    settings = get_settings()
    setup_logging(settings.log_level)
    await ensure_indexes_async()
    yield
    await close_async_client()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Web Intelligence Agent",
        description="AI Website Audit + Outreach Automation Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, tags=["health"])
    app.include_router(audits.router, prefix="/audits", tags=["audits"])

    return app


app = create_app()
