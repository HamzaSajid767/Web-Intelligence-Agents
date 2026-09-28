"""Website audit aggregate document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.constants import AuditStatus
from app.database.models.agent_execution_log import AgentExecutionLog
from app.database.models.audit_run import AuditRun
from app.database.models.base import as_uuid, new_uuid, utc_now
from app.database.models.business_profile import BusinessProfile
from app.database.models.generated_email import GeneratedEmail
from app.database.models.pain_point import PainPoint
from app.database.models.recommendation import Recommendation
from app.database.models.website_page import WebsitePage


@dataclass
class WebsiteAudit:
    """Top-level website audit aggregate root."""

    user_id: uuid.UUID
    website_url: str
    id: uuid.UUID = field(default_factory=new_uuid)
    status: str = AuditStatus.PENDING.value
    error_message: str | None = None
    metadata_json: dict[str, Any] | None = None
    emails: list[str] = field(default_factory=list)
    phone_numbers: list[str] = field(default_factory=list)
    social_links: list[str] = field(default_factory=list)
    pages: list[WebsitePage] = field(default_factory=list)
    business_profile: BusinessProfile | None = None
    pain_points: list[PainPoint] = field(default_factory=list)
    recommendations: list[Recommendation] = field(default_factory=list)
    generated_email: GeneratedEmail | None = None
    audit_runs: list[AuditRun] = field(default_factory=list)
    agent_logs: list[AgentExecutionLog] = field(default_factory=list)
    submitted_urls: list[str] = field(default_factory=list)
    latest_submitted_url: str | None = None
    final_url: str | None = None
    redirect_history: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_document(self) -> dict:
        """Serialize full aggregate to MongoDB document."""
        return {
            "_id": str(self.id),
            "user_id": str(self.user_id),
            "website_url": self.website_url,
            "status": self.status,
            "error_message": self.error_message,
            "metadata": self.metadata_json,
            "emails": self.emails,
            "phone_numbers": self.phone_numbers,
            "social_links": self.social_links,
            "pages": [page.to_document() for page in self.pages],
            "business_profile": (
                self.business_profile.to_document() if self.business_profile else None
            ),
            "pain_points": [pp.to_document() for pp in self.pain_points],
            "recommendations": [rec.to_document() for rec in self.recommendations],
            "generated_email": (
                self.generated_email.to_document() if self.generated_email else None
            ),
            "audit_runs": [run.to_document() for run in self.audit_runs],
            "agent_logs": [log.to_document() for log in self.agent_logs],
            "submitted_urls": list(self.submitted_urls),
            "latest_submitted_url": self.latest_submitted_url,
            "final_url": self.final_url,
            "redirect_history": list(self.redirect_history),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_document(cls, doc: dict) -> WebsiteAudit:
        """Deserialize aggregate from MongoDB document."""
        website_url = doc["website_url"]
        submitted = list(doc.get("submitted_urls") or [])
        if website_url and website_url not in submitted:
            # Legacy docs: ensure the stored identity is discoverable as an alias.
            submitted = [website_url, *submitted]
        return cls(
            id=uuid.UUID(str(doc["_id"])),
            user_id=as_uuid(doc["user_id"]),
            website_url=website_url,
            status=doc.get("status", AuditStatus.PENDING.value),
            error_message=doc.get("error_message"),
            metadata_json=doc.get("metadata"),
            emails=list(doc.get("emails") or []),
            phone_numbers=list(doc.get("phone_numbers") or []),
            social_links=list(doc.get("social_links") or []),
            pages=[WebsitePage.from_document(p) for p in doc.get("pages") or []],
            business_profile=BusinessProfile.from_document(doc.get("business_profile")),
            pain_points=[PainPoint.from_document(p) for p in doc.get("pain_points") or []],
            recommendations=[
                Recommendation.from_document(r) for r in doc.get("recommendations") or []
            ],
            generated_email=GeneratedEmail.from_document(doc.get("generated_email")),
            audit_runs=[AuditRun.from_document(r) for r in doc.get("audit_runs") or []],
            agent_logs=[
                AgentExecutionLog.from_document(log) for log in doc.get("agent_logs") or []
            ],
            submitted_urls=submitted,
            latest_submitted_url=doc.get("latest_submitted_url"),
            final_url=doc.get("final_url"),
            redirect_history=list(doc.get("redirect_history") or []),
            created_at=doc.get("created_at", utc_now()),
            updated_at=doc.get("updated_at", utc_now()),
        )
