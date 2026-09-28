"""Audit queue job document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.constants import QueueJobStatus
from app.database.models.base import as_optional_uuid, new_uuid, utc_now


@dataclass
class AuditQueueJob:
    """One queued URL awaiting audit processing."""

    website_url: str
    queued_at: datetime
    id: uuid.UUID = field(default_factory=new_uuid)
    batch_id: uuid.UUID | None = None
    status: str = QueueJobStatus.QUEUED.value
    retry_count: int = 0
    max_retries: int = 3
    worker_id: str | None = None
    audit_id: uuid.UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    error_trace: str | None = None
    final_state_json: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_document(self) -> dict:
        """Serialize to MongoDB document."""
        return {
            "_id": str(self.id),
            "batch_id": str(self.batch_id) if self.batch_id else None,
            "website_url": self.website_url,
            "status": self.status,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "worker_id": self.worker_id,
            "audit_id": str(self.audit_id) if self.audit_id else None,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "error_trace": self.error_trace,
            "final_state": self.final_state_json,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_document(cls, doc: dict) -> AuditQueueJob:
        """Deserialize from MongoDB document."""
        return cls(
            id=uuid.UUID(str(doc["_id"])),
            batch_id=as_optional_uuid(doc.get("batch_id")),
            website_url=doc["website_url"],
            status=doc.get("status", QueueJobStatus.QUEUED.value),
            retry_count=doc.get("retry_count", 0),
            max_retries=doc.get("max_retries", 3),
            worker_id=doc.get("worker_id"),
            audit_id=as_optional_uuid(doc.get("audit_id")),
            queued_at=doc.get("queued_at", utc_now()),
            started_at=doc.get("started_at"),
            completed_at=doc.get("completed_at"),
            duration_ms=doc.get("duration_ms"),
            error_message=doc.get("error_message"),
            error_trace=doc.get("error_trace"),
            final_state_json=doc.get("final_state"),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
        )
