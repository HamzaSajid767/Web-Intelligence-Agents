"""MongoDB session and client management."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import MongoClient
from pymongo.database import Database

from app.core.config import get_settings
from app.database.models.website_audit import WebsiteAudit

_async_client: AsyncIOMotorClient | None = None
_sync_client: MongoClient | None = None


def _database_name(uri: str, fallback: str) -> str:
    """Extract database name from URI path, or use fallback."""
    path = urlparse(uri).path.lstrip("/")
    if path:
        return path.split("?")[0] or fallback
    return fallback


def get_async_client() -> AsyncIOMotorClient:
    """Return shared async Motor client."""
    global _async_client
    if _async_client is None:
        settings = get_settings()
        _async_client = AsyncIOMotorClient(settings.mongodb_uri)
    return _async_client


def get_sync_client() -> MongoClient:
    """Return shared sync PyMongo client."""
    global _sync_client
    if _sync_client is None:
        settings = get_settings()
        _sync_client = MongoClient(settings.mongodb_uri)
    return _sync_client


def get_async_db() -> AsyncIOMotorDatabase:
    """Return async database handle."""
    settings = get_settings()
    name = _database_name(settings.mongodb_uri, settings.mongodb_db_name)
    return get_async_client()[name]


def get_sync_db() -> Database:
    """Return sync database handle."""
    settings = get_settings()
    name = _database_name(settings.mongodb_uri, settings.mongodb_db_name)
    return get_sync_client()[name]


class SyncMongoSession:
    """Thin sync session wrapper preserving commit/rollback/close call sites.

    Structural writes go through repositories immediately. Top-level audit field
    mutations (status/metadata) made on tracked WebsiteAudit instances are
    flushed on commit.
    """

    def __init__(self, db: Database | None = None) -> None:
        self.db = db if db is not None else get_sync_db()
        self._dirty_audits: dict[str, WebsiteAudit] = {}
        self._closed = False

    def track_audit(self, audit: WebsiteAudit) -> WebsiteAudit:
        """Track an audit for dirty flush on commit."""
        self._dirty_audits[str(audit.id)] = audit
        return audit

    def commit(self) -> None:
        """Persist tracked audit top-level fields."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        for audit in self._dirty_audits.values():
            audit.updated_at = now
            self.db.website_audits.update_one(
                {"_id": str(audit.id)},
                {
                    "$set": {
                        "status": audit.status,
                        "error_message": audit.error_message,
                        "metadata": audit.metadata_json,
                        "emails": audit.emails,
                        "phone_numbers": audit.phone_numbers,
                        "social_links": audit.social_links,
                        "updated_at": audit.updated_at,
                    }
                },
            )
        self._dirty_audits.clear()

    def rollback(self) -> None:
        """Discard tracked dirty audits."""
        self._dirty_audits.clear()

    def close(self) -> None:
        """Mark session closed (shared client remains open)."""
        self._dirty_audits.clear()
        self._closed = True

    @property
    def is_active(self) -> bool:
        """Return True while session has not been closed."""
        return not self._closed

    def flush(self) -> None:
        """Alias for commit of tracked audits."""
        self.commit()


def SyncSessionLocal() -> SyncMongoSession:
    """Factory matching previous sync session call pattern."""
    return SyncMongoSession()


async def get_async_session() -> AsyncGenerator[AsyncIOMotorDatabase, None]:
    """Yield async database for FastAPI dependencies."""
    yield get_async_db()


async def close_async_client() -> None:
    """Close shared async client."""
    global _async_client
    if _async_client is not None:
        _async_client.close()
        _async_client = None


def close_sync_client() -> None:
    """Close shared sync client."""
    global _sync_client
    if _sync_client is not None:
        _sync_client.close()
        _sync_client = None


def resolve_db(session: Any) -> Database | AsyncIOMotorDatabase:
    """Return underlying database from session wrapper or raw handle."""
    if isinstance(session, SyncMongoSession):
        return session.db
    return session
