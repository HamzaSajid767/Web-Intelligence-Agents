"""Audit report assembly service."""

import uuid
from typing import Any

from app.database.repositories import WebsiteAuditRepository


class ReportService:
    """Assembles full audit reports from persisted data."""

    def __init__(self, session: Any) -> None:
        self.audit_repo = WebsiteAuditRepository(session)

    async def get_full_report(self, audit_id: uuid.UUID) -> dict[str, Any] | None:
        """Build complete audit report DTO."""
        audit = await self.audit_repo.get_by_id_async(audit_id)
        if not audit:
            return None

        return {
            "audit_id": str(audit.id),
            "website_url": audit.website_url,
            "status": audit.status,
            "error_message": audit.error_message,
            "created_at": audit.created_at.isoformat(),
            "updated_at": audit.updated_at.isoformat(),
            "emails": list(audit.emails or []),
            "phone_numbers": list(audit.phone_numbers or []),
            "social_links": list(audit.social_links or []),
            "pages": [
                {
                    "id": str(page.id),
                    "url": page.url,
                    "title": page.title,
                    "metadata": page.metadata_json,
                    "headings": page.headings_json,
                    "links_count": len(page.links_json or []),
                    "clean_text_preview": (page.clean_text or "")[:500],
                }
                for page in audit.pages
            ],
            "business_profile": (
                {
                    "industry": audit.business_profile.industry,
                    "services": audit.business_profile.services_json,
                    "target_audience": audit.business_profile.target_audience,
                    "value_proposition": audit.business_profile.value_proposition,
                    "raw_ai_output": audit.business_profile.raw_ai_output_json,
                }
                if audit.business_profile
                else None
            ),
            "pain_points": [
                {
                    "id": str(pp.id),
                    "category": pp.category,
                    "severity": pp.severity,
                    "description": pp.description,
                    "evidence": pp.evidence_json,
                    "score": pp.score,
                }
                for pp in audit.pain_points
            ],
            "scores": audit.metadata_json.get("scores") if audit.metadata_json else None,
            "seo_analysis": audit.metadata_json.get("seo_analysis") if audit.metadata_json else None,
            "chatbot_analysis": (
                audit.metadata_json.get("chatbot_analysis") if audit.metadata_json else None
            ),
            "crawl_analysis": (
                audit.metadata_json.get("crawl_analysis") if audit.metadata_json else None
            ),
            "crawl_errors": audit.metadata_json.get("crawl_errors") if audit.metadata_json else None,
            "page_context": audit.metadata_json.get("page_context") if audit.metadata_json else None,
            "final_state": audit.metadata_json.get("final_state") if audit.metadata_json else None,
            "recommendations": [
                {
                    "id": str(rec.id),
                    "title": rec.title,
                    "description": rec.description,
                    "priority": rec.priority,
                    "impact_score": rec.impact_score,
                    "effort_estimate": rec.effort_estimate,
                }
                for rec in audit.recommendations
            ],
            "email": (
                {
                    "id": str(audit.generated_email.id),
                    "subject": audit.generated_email.subject,
                    "body": audit.generated_email.body,
                    "status": audit.generated_email.status,
                    "approved_at": (
                        audit.generated_email.approved_at.isoformat()
                        if audit.generated_email.approved_at
                        else None
                    ),
                }
                if audit.generated_email
                else None
            ),
            "agent_logs": [
                {
                    "agent_name": log.agent_name,
                    "status": log.status,
                    "duration_ms": log.duration_ms,
                    "token_usage": log.token_usage_json,
                    "error_message": log.error_message,
                }
                for log in audit.agent_logs
            ],
            "audit_runs": [
                {
                    "id": str(run.id),
                    "status": run.status,
                    "celery_task_id": run.celery_task_id,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                }
                for run in audit.audit_runs
            ],
        }
