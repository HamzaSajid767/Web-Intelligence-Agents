"""Audit run embedded document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.core.constants import AuditRunStatus
from app.database.models.base import new_uuid, utc_now


@dataclass
class AuditRun:
    """Single execution attempt of an audit pipeline."""

    id: uuid.UUID = field(default_factory=new_uuid)
    celery_task_id: str | None = None
    status: str = AuditRunStatus.PENDING.value
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_trace: str | None = None
    created_at: datetime = field(default_factory=utc_now)

    def to_document(self) -> dict:
        """Serialize to embedded MongoDB subdocument."""
        return {
            "id": str(self.id),
            "celery_task_id": self.celery_task_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_trace": self.error_trace,
            "created_at": self.created_at,
        }

    @classmethod
    def from_document(cls, doc: dict) -> AuditRun:
        """Deserialize from embedded MongoDB subdocument."""
        return cls(
            id=uuid.UUID(str(doc.get("id", new_uuid()))),
            celery_task_id=doc.get("celery_task_id"),
            status=doc.get("status", AuditRunStatus.PENDING.value),
            started_at=doc.get("started_at"),
            finished_at=doc.get("finished_at"),
            error_trace=doc.get("error_trace"),
            created_at=doc.get("created_at", utc_now()),
        )
