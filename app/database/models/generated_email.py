"""Generated email embedded document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.constants import EmailStatus
from app.database.models.base import as_optional_uuid, new_uuid


@dataclass
class GeneratedEmail:
    """Outreach email draft embedded on a website audit."""

    subject: str
    body: str
    id: uuid.UUID = field(default_factory=new_uuid)
    status: str = EmailStatus.DRAFT.value
    approved_at: datetime | None = None
    approved_by_user_id: uuid.UUID | None = None

    def to_document(self) -> dict:
        """Serialize to embedded MongoDB subdocument."""
        return {
            "id": str(self.id),
            "subject": self.subject,
            "body": self.body,
            "status": self.status,
            "approved_at": self.approved_at,
            "approved_by_user_id": (
                str(self.approved_by_user_id) if self.approved_by_user_id else None
            ),
        }

    @classmethod
    def from_document(cls, doc: dict | None) -> GeneratedEmail | None:
        """Deserialize from embedded MongoDB subdocument."""
        if not doc:
            return None
        return cls(
            id=uuid.UUID(str(doc.get("id", new_uuid()))),
            subject=doc.get("subject", ""),
            body=doc.get("body", ""),
            status=doc.get("status", EmailStatus.DRAFT.value),
            approved_at=doc.get("approved_at"),
            approved_by_user_id=as_optional_uuid(doc.get("approved_by_user_id")),
        )
