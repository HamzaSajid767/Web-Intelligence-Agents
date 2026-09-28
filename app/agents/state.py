"""LangGraph audit workflow state."""

from typing import Any, TypedDict


class AuditState(TypedDict, total=False):
    """Shared state passed between LangGraph agent nodes."""

    audit_id: str
    website_url: str
    crawl_data: dict[str, Any]
    business_profile: dict[str, Any]
    pain_points: list[dict[str, Any]]
    seo_analysis: dict[str, Any]
    chatbot_analysis: dict[str, Any]
    scores: dict[str, Any]
    recommendations: list[dict[str, Any]]
    email_draft: dict[str, Any]
    agent_logs: list[dict[str, Any]]
    status: str
    error: str | None
    current_agent: str | None
