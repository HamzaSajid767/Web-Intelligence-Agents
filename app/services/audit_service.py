"""Audit business logic service."""

import uuid
from typing import Any

from app.core.constants import AuditStatus
from app.core.logging import get_logger
from app.core.url_identity import normalize_identity_url
from app.database.repositories import AuditRunRepository, UserRepository, WebsiteAuditRepository
from app.workflows.job_manager import JobManager

logger = get_logger(__name__)


class AuditService:
    """Application service for audit operations."""

    def __init__(self, session: Any, job_manager: JobManager | None = None) -> None:
        self.session = session
        self.job_manager = job_manager or JobManager()
        self.audit_repo = WebsiteAuditRepository(session)
        self.run_repo = AuditRunRepository(session)
        self.user_repo = UserRepository(session)

    @staticmethod
    def validate_url(website_url: str) -> str:
        """Validate and normalize website URL to shared identity form."""
        return normalize_identity_url(website_url)

    async def create_audit(self, website_url: str) -> tuple[uuid.UUID, str]:
        """Create audit record and enqueue background processing."""
        url = self.validate_url(website_url)
        user = await self.user_repo.create_default_user_async()

        audit = await self.audit_repo.claim_or_create_by_url_async(
            user_id=user.id,
            submitted_url=url,
        )
        run = await self.run_repo.create_async(audit.id)

        task_id = self.job_manager.enqueue_audit(audit.id, run.id, url)
        await self.run_repo.mark_running_async(run.id, task_id)

        logger.info("Audit upserted", extra={"audit_id": str(audit.id)})
        return audit.id, AuditStatus.PENDING.value

    async def get_audit_status(self, audit_id: uuid.UUID) -> str | None:
        """Get current audit status."""
        audit = await self.audit_repo.get_by_id_async(audit_id)
        return audit.status if audit else None
