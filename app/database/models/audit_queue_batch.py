"""Audit queue batch document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.core.constants import QueueBatchStatus
from app.database.models.base import new_uuid, utc_now


@dataclass
class AuditQueueBatch:
    """Bulk queue batch of audit jobs."""

    total_jobs: int
    id: uuid.UUID = field(default_factory=new_uuid)
    name: str | None = None
    source: str = "cli"
    status: str = QueueBatchStatus.PENDING.value
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_document(self) -> dict:
        """Serialize to MongoDB document."""
        return {
            "_id": str(self.id),
            "name": self.name,
            "source": self.source,
            "total_jobs": self.total_jobs,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_document(cls, doc: dict) -> AuditQueueBatch:
        """Deserialize from MongoDB document."""
        return cls(
            id=uuid.UUID(str(doc["_id"])),
            name=doc.get("name"),
            source=doc.get("source", "cli"),
            total_jobs=doc.get("total_jobs", 0),
            status=doc.get("status", QueueBatchStatus.PENDING.value),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
        )
