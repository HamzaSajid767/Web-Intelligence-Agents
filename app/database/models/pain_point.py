"""Pain point embedded document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.database.models.base import new_uuid


@dataclass
class PainPoint:
    """Identified website pain point."""

    category: str = "general"
    severity: str = "medium"
    description: str = ""
    id: uuid.UUID = field(default_factory=new_uuid)
    evidence_json: dict[str, Any] | list[Any] | None = None
    score: float | None = None

    def to_document(self) -> dict:
        """Serialize to embedded MongoDB subdocument."""
        return {
            "id": str(self.id),
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence_json,
            "score": self.score,
        }

    @classmethod
    def from_document(cls, doc: dict) -> PainPoint:
        """Deserialize from embedded MongoDB subdocument."""
        return cls(
            id=uuid.UUID(str(doc.get("id", new_uuid()))),
            category=doc.get("category", "general"),
            severity=doc.get("severity", "medium"),
            description=doc.get("description", ""),
            evidence_json=doc.get("evidence"),
            score=doc.get("score"),
        )
