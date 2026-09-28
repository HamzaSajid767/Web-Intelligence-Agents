"""Recommendation embedded document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.database.models.base import new_uuid


@dataclass
class Recommendation:
    """Actionable recommendation for a website audit."""

    title: str = ""
    description: str = ""
    id: uuid.UUID = field(default_factory=new_uuid)
    priority: str = "medium"
    impact_score: float | None = None
    effort_estimate: str | None = None
    raw_ai_output_json: dict[str, Any] | None = None

    def to_document(self) -> dict:
        """Serialize to embedded MongoDB subdocument."""
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "impact_score": self.impact_score,
            "effort_estimate": self.effort_estimate,
            "raw_ai_output": self.raw_ai_output_json,
        }

    @classmethod
    def from_document(cls, doc: dict) -> Recommendation:
        """Deserialize from embedded MongoDB subdocument."""
        return cls(
            id=uuid.UUID(str(doc.get("id", new_uuid()))),
            title=doc.get("title", ""),
            description=doc.get("description", ""),
            priority=doc.get("priority", "medium"),
            impact_score=doc.get("impact_score"),
            effort_estimate=doc.get("effort_estimate"),
            raw_ai_output_json=doc.get("raw_ai_output"),
        )
