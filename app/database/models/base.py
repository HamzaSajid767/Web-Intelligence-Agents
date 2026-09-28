"""Shared helpers for MongoDB document models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_uuid() -> uuid.UUID:
    """Generate a new UUID."""
    return uuid.uuid4()


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Normalize UUID or string to UUID."""
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def as_optional_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    """Normalize optional UUID."""
    if value is None:
        return None
    return as_uuid(value)
