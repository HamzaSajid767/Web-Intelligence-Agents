"""Business profile embedded document."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BusinessProfile:
    """Business profile derived from crawl/AI analysis."""

    industry: str | None = None
    services_json: list[Any] | dict[str, Any] | None = None
    target_audience: str | None = None
    value_proposition: str | None = None
    raw_ai_output_json: dict[str, Any] | None = None

    def to_document(self) -> dict:
        """Serialize to embedded MongoDB subdocument."""
        return {
            "industry": self.industry,
            "services": self.services_json,
            "target_audience": self.target_audience,
            "value_proposition": self.value_proposition,
            "raw_ai_output": self.raw_ai_output_json,
        }

    @classmethod
    def from_document(cls, doc: dict | None) -> BusinessProfile | None:
        """Deserialize from embedded MongoDB subdocument."""
        if not doc:
            return None
        return cls(
            industry=doc.get("industry"),
            services_json=doc.get("services"),
            target_audience=doc.get("target_audience"),
            value_proposition=doc.get("value_proposition"),
            raw_ai_output_json=doc.get("raw_ai_output"),
        )
