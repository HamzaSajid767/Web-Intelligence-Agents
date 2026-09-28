"""Agent execution log embedded document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.database.models.base import new_uuid


@dataclass
class AgentExecutionLog:
    """Per-agent execution log entry."""

    agent_name: str
    status: str
    id: uuid.UUID = field(default_factory=new_uuid)
    input_snapshot_json: dict[str, Any] | None = None
    output_snapshot_json: dict[str, Any] | None = None
    duration_ms: int | None = None
    token_usage_json: dict[str, Any] | None = None
    error_message: str | None = None

    def to_document(self) -> dict:
        """Serialize to embedded MongoDB subdocument."""
        return {
            "id": str(self.id),
            "agent_name": self.agent_name,
            "status": self.status,
            "input_snapshot": self.input_snapshot_json,
            "output_snapshot": self.output_snapshot_json,
            "duration_ms": self.duration_ms,
            "token_usage": self.token_usage_json,
            "error_message": self.error_message,
        }

    @classmethod
    def from_document(cls, doc: dict) -> AgentExecutionLog:
        """Deserialize from embedded MongoDB subdocument."""
        return cls(
            id=uuid.UUID(str(doc.get("id", new_uuid()))),
            agent_name=doc.get("agent_name", "unknown"),
            status=doc.get("status", "completed"),
            input_snapshot_json=doc.get("input_snapshot"),
            output_snapshot_json=doc.get("output_snapshot"),
            duration_ms=doc.get("duration_ms"),
            token_usage_json=doc.get("token_usage"),
            error_message=doc.get("error_message"),
        )
