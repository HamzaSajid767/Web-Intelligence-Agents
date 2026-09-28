"""Shared single-audit execution for CLI and queue workers."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.agents.state import AuditState
from app.core.logging import get_logger
from app.database.models import User
from app.database.repositories import AuditRunRepository, UserRepository, WebsiteAuditRepository
from app.database.session import SyncSessionLocal
from app.services.audit_service import AuditService
from app.workflows.audit_workflow import AuditWorkflow

logger = get_logger(__name__)


@dataclass
class AuditRunResult:
    """Result of a single audit execution."""

    audit_id: uuid.UUID
    run_id: uuid.UUID
    website_url: str
    final_state: AuditState
    duration_ms: int


class AuditRunner:
    """Create audit records and run the LangGraph pipeline."""

    def __init__(self, workflow: AuditWorkflow | None = None) -> None:
        self.workflow = workflow or AuditWorkflow()

    @staticmethod
    def get_or_create_default_user(session: Any) -> User:
        """Return the default tenant user, creating it if missing."""
        repo = UserRepository(session)
        return repo.create_default_user_sync()

    def run(self, website_url: str, *, user_id: uuid.UUID | None = None) -> AuditRunResult:
        """Validate URL, create audit records, execute workflow, return result."""
        url = AuditService.validate_url(website_url)
        session = SyncSessionLocal()
        started = time.perf_counter()

        try:
            if user_id is None:
                user = self.get_or_create_default_user(session)
                user_id = user.id

            audit_repo = WebsiteAuditRepository(session)
            run_repo = AuditRunRepository(session)
            audit = audit_repo.claim_or_create_by_url_sync(
                user_id=user_id,
                submitted_url=url,
            )
            run = run_repo.create_sync(audit.id)
            session.commit()

            audit_id = audit.id
            run_id = run.id
            session.close()

            logger.info(
                "Starting audit",
                extra={"audit_id": str(audit_id), "website_url": url},
            )
            final_state = self.workflow.execute_sync(audit_id, url, run_id)
            duration_ms = int((time.perf_counter() - started) * 1000)
            if final_state.get("audit_id"):
                audit_id = uuid.UUID(str(final_state["audit_id"]))

            return AuditRunResult(
                audit_id=audit_id,
                run_id=run_id,
                website_url=final_state.get("website_url") or url,
                final_state=final_state,
                duration_ms=duration_ms,
            )
        except Exception:
            session.rollback()
            raise
        finally:
            if session.is_active:
                session.close()
