"""MongoDB index creation and default seed data."""

from __future__ import annotations

import uuid
from typing import Any

from pymongo.errors import DuplicateKeyError, OperationFailure

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.models.base import utc_now
from app.database.session import get_async_db, get_sync_db

logger = get_logger(__name__)


async def ensure_indexes_async(db: Any | None = None) -> None:
    """Create indexes and seed default user (async)."""
    database = db if db is not None else get_async_db()
    await database.users.create_index("email", unique=True)
    await database.website_audits.create_index("user_id")
    await _ensure_unique_website_url_index_async(database)
    await database.website_audits.create_index("submitted_urls")
    await database.website_audits.create_index("status")
    await database.audit_queue_batches.create_index("status")
    await database.audit_queue_jobs.create_index("batch_id")
    await database.audit_queue_jobs.create_index("audit_id")
    await database.audit_queue_jobs.create_index("status")
    await database.audit_queue_jobs.create_index("queued_at")
    await database.audit_queue_jobs.create_index([("status", 1), ("queued_at", 1)])
    await _seed_default_user_async(database)


def ensure_indexes_sync(db: Any | None = None) -> None:
    """Create indexes and seed default user (sync)."""
    database = db if db is not None else get_sync_db()
    database.users.create_index("email", unique=True)
    database.website_audits.create_index("user_id")
    _ensure_unique_website_url_index_sync(database)
    database.website_audits.create_index("submitted_urls")
    database.website_audits.create_index("status")
    database.audit_queue_batches.create_index("status")
    database.audit_queue_jobs.create_index("batch_id")
    database.audit_queue_jobs.create_index("audit_id")
    database.audit_queue_jobs.create_index("status")
    database.audit_queue_jobs.create_index("queued_at")
    database.audit_queue_jobs.create_index([("status", 1), ("queued_at", 1)])
    _seed_default_user_sync(database)


async def _ensure_unique_website_url_index_async(database: Any) -> None:
    """Drop non-unique website_url index and create a unique one."""
    try:
        await database.website_audits.drop_index("website_url_1")
    except OperationFailure:
        pass
    try:
        await database.website_audits.create_index("website_url", unique=True)
    except OperationFailure as exc:
        logger.error(
            "Failed to create unique website_url index. "
            "Remove duplicate website_audits documents for the same website_url, "
            "then re-run make ensure-db. Error: %s",
            exc,
        )
        raise


def _ensure_unique_website_url_index_sync(database: Any) -> None:
    """Drop non-unique website_url index and create a unique one."""
    try:
        database.website_audits.drop_index("website_url_1")
    except OperationFailure:
        pass
    try:
        database.website_audits.create_index("website_url", unique=True)
    except OperationFailure as exc:
        logger.error(
            "Failed to create unique website_url index. "
            "Remove duplicate website_audits documents for the same website_url, "
            "then re-run make ensure-db. Error: %s",
            exc,
        )
        raise


async def _seed_default_user_async(db: Any) -> None:
    settings = get_settings()
    existing = await db.users.find_one({"email": settings.default_user_email})
    if existing:
        return
    now = utc_now()
    try:
        await db.users.insert_one(
            {
                "_id": "00000000-0000-4000-8000-000000000001",
                "email": settings.default_user_email,
                "name": settings.default_user_name,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    except DuplicateKeyError:
        return


def _seed_default_user_sync(db: Any) -> None:
    settings = get_settings()
    existing = db.users.find_one({"email": settings.default_user_email})
    if existing:
        return
    now = utc_now()
    try:
        db.users.insert_one(
            {
                "_id": str(uuid.UUID("00000000-0000-4000-8000-000000000001")),
                "email": settings.default_user_email,
                "name": settings.default_user_name,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )
    except DuplicateKeyError:
        return
