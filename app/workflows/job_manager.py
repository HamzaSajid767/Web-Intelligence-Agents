"""Background job enqueue and lifecycle management."""

import uuid

from app.core.logging import get_logger
from app.tasks.celery_tasks import run_audit_pipeline

logger = get_logger(__name__)


class JobManager:
    """Enqueue and track Celery audit jobs."""

    def enqueue_audit(self, audit_id: uuid.UUID, run_id: uuid.UUID, website_url: str) -> str:
        """Enqueue audit pipeline Celery task."""
        task = run_audit_pipeline.delay(
            str(audit_id),
            str(run_id),
            website_url,
        )
        logger.info(
            "Audit job enqueued",
            extra={"audit_id": str(audit_id), "task_id": task.id},
        )
        return task.id
