"""Celery background tasks."""

import uuid

from app.core.logging import get_logger
from app.tasks.celery_app import celery_app
from app.workflows.audit_workflow import AuditWorkflow

logger = get_logger(__name__)


@celery_app.task(bind=True, name="run_audit_pipeline", max_retries=3)
def run_audit_pipeline(self, audit_id: str, run_id: str, website_url: str) -> dict:
    """Execute the LangGraph audit pipeline in a Celery worker."""
    logger.info(
        "Starting audit pipeline task",
        extra={"audit_id": audit_id, "task_id": self.request.id},
    )
    workflow = AuditWorkflow()
    try:
        workflow.execute_sync(
            audit_id=uuid.UUID(audit_id),
            website_url=website_url,
            run_id=uuid.UUID(run_id),
        )
        return {"audit_id": audit_id, "status": "completed"}
    except Exception as exc:
        logger.exception("Audit pipeline task failed", extra={"audit_id": audit_id})
        raise self.retry(exc=exc, countdown=60) from exc
