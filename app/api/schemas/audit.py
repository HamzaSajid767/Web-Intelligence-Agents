"""API request/response schemas."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class CreateAuditRequest(BaseModel):
    """Request body for creating an audit."""

    website_url: HttpUrl


class CreateAuditResponse(BaseModel):
    """Response after creating an audit."""

    audit_id: UUID
    status: str


class EmailResponse(BaseModel):
    """Generated email response."""

    audit_id: UUID
    email_id: UUID | None = None
    subject: str
    body: str
    status: str
    approved_at: str | None = None


class ApproveEmailResponse(BaseModel):
    """Response after approving an email."""

    audit_id: UUID
    email_id: UUID
    subject: str
    body: str
    status: str
    approved_at: str | None = None
    message: str


class AuditReportResponse(BaseModel):
    """Full audit report response."""

    audit_id: UUID
    website_url: str
    status: str
    error_message: str | None = None
    created_at: str
    updated_at: str
    emails: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    social_links: list[str] = Field(default_factory=list)
    pages: list[dict[str, Any]] = Field(default_factory=list)
    business_profile: dict[str, Any] | None = None
    pain_points: list[dict[str, Any]] = Field(default_factory=list)
    scores: dict[str, Any] | None = None
    seo_analysis: dict[str, Any] | None = None
    chatbot_analysis: dict[str, Any] | None = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    email: dict[str, Any] | None = None
    agent_logs: list[dict[str, Any]] = Field(default_factory=list)
    audit_runs: list[dict[str, Any]] = Field(default_factory=list)
