"""User document model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.database.models.base import new_uuid, utc_now


@dataclass
class User:
    """Application user (v1 single-tenant default user)."""

    email: str
    name: str
    id: uuid.UUID = field(default_factory=new_uuid)
    is_active: bool = True
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_document(self) -> dict:
        """Serialize to MongoDB document."""
        return {
            "_id": str(self.id),
            "email": self.email,
            "name": self.name,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_document(cls, doc: dict) -> User:
        """Deserialize from MongoDB document."""
        return cls(
            id=uuid.UUID(str(doc["_id"])),
            email=doc["email"],
            name=doc["name"],
            is_active=doc.get("is_active", True),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
        )
