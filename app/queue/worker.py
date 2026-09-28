"""Per-process queue worker loop."""

from __future__ import annotations

import time
import traceback
import uuid
from typing import Any

from app.core.config import Settings, get_settings
from app.core.constants import AgentName, AuditStatus, QueueJobStatus
from app.core.exceptions import InvalidSiteError
from app.core.logging import audit_id_ctx, get_logger, job_id_ctx, worker_id_ctx
from app.database.repositories import AuditQueueJobRepository
from app.database.session import SyncSessionLocal
from app.queue.manager import QueueManager
from app.utils.audit_state import serialize_audit_state
from app.services.audit_runner import AuditRunner

logger = get_logger(__name__)


class QueueWorker:
    """Claim and process queue jobs in a worker process."""

    def __init__(
        self,
        worker_id: str,
        *,
        settings: Settings | None = None,
        stop_event: Any | None = None,
        batch_id: uuid.UUID | None = None,
    ) -> None:
        self.worker_id = worker_id
        self.settings = settings or get_settings()
        self.stop_event = stop_event
        self.batch_id = batch_id
        self.audit_runner = AuditRunner()
        self.queue_manager = QueueManager(self.settings)

    def _should_stop(self) -> bool:
        return self.stop_event is not None and self.stop_event.is_set()

    def run(self) -> None:
        """Process jobs until the queue is empty or stop is requested."""
        worker_id_ctx.set(self.worker_id)
        logger.info("Worker started", extra={"worker_id": self.worker_id})

        while not self._should_stop():
            job = self._claim_next_job()
            if job is None:
                if self._should_stop() or not self._has_pending_jobs():
                    break
                time.sleep(self.settings.queue_poll_interval_seconds)
                continue
            self._process_job(job)

        logger.info("Worker stopped", extra={"worker_id": self.worker_id})

    def _claim_next_job(self) -> Any | None:
        session = SyncSessionLocal()
        try:
            job_repo = AuditQueueJobRepository(session)
            job = job_repo.claim_next_sync(self.worker_id, batch_id=self.batch_id)
            if job:
                session.commit()
                if job.batch_id:
                    self.queue_manager.update_batch_status(job.batch_id)
            return job
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _has_pending_jobs(self) -> bool:
        session = SyncSessionLocal()
        try:
            job_repo = AuditQueueJobRepository(session)
            return job_repo.has_pending_jobs_sync(self.batch_id)
        finally:
            session.close()

    @staticmethod
    def _stage_durations(final_state: Any, total_ms: int) -> tuple[int | None, int | None]:
        """Derive crawl vs agent stage timings from agent_logs when available."""
        logs = []
        if isinstance(final_state, dict):
            logs = final_state.get("agent_logs") or []
        else:
            logs = getattr(final_state, "get", lambda *_: None)("agent_logs") or []

        crawl_ms = 0
        agents_ms = 0
        found_crawl = False
        found_agents = False
        for entry in logs:
            if not isinstance(entry, dict):
                continue
            duration = entry.get("duration_ms")
            if duration is None:
                continue
            name = entry.get("agent_name")
            if name == AgentName.CRAWLER.value:
                crawl_ms += int(duration)
                found_crawl = True
            else:
                agents_ms += int(duration)
                found_agents = True

        if not found_crawl and not found_agents:
            return None, None
        if not found_agents and found_crawl:
            agents_ms = max(0, total_ms - crawl_ms)
        return crawl_ms if found_crawl else None, agents_ms if (found_agents or found_crawl) else None

    def _process_job(self, job: Any) -> None:
        job_id_ctx.set(str(job.id))
        logger.info(
            "Processing queue job",
            extra={
                "worker_id": self.worker_id,
                "job_id": str(job.id),
                "website_url": job.website_url,
                "retry_count": job.retry_count,
                "status": QueueJobStatus.RUNNING.value,
            },
        )

        try:
            result = self.audit_runner.run(job.website_url)
            audit_id_ctx.set(str(result.audit_id))
            final_state = serialize_audit_state(result.final_state)
            status = (
                result.final_state.get("status")
                if isinstance(result.final_state, dict)
                else getattr(result.final_state, "get", lambda *_: None)("status")
            )
            if status not in {
                AuditStatus.AWAITING_REVIEW.value,
                AuditStatus.COMPLETED.value,
            }:
                raise RuntimeError(
                    f"Audit finished without reviewable status (status={status!r})"
                )
            crawl_ms, agents_ms = self._stage_durations(result.final_state, result.duration_ms)
            self._mark_success(
                job.id,
                audit_id=result.audit_id,
                duration_ms=result.duration_ms,
                final_state_json=final_state,
                batch_id=job.batch_id,
            )
            logger.info(
                "Queue job completed",
                extra={
                    "worker_id": self.worker_id,
                    "job_id": str(job.id),
                    "website_url": job.website_url,
                    "crawl_ms": crawl_ms,
                    "agents_ms": agents_ms,
                    "total_ms": result.duration_ms,
                    "duration_ms": result.duration_ms,
                    "status": QueueJobStatus.SUCCESS.value,
                },
            )
        except InvalidSiteError as exc:
            error_trace = traceback.format_exc()
            if exc.audit_id:
                audit_id_ctx.set(str(exc.audit_id))
            self._mark_failure(
                job.id,
                error_message=str(exc),
                error_trace=error_trace,
                will_retry=False,
                batch_id=job.batch_id,
            )
            logger.warning(
                "Queue job failed: invalid site",
                extra={
                    "worker_id": self.worker_id,
                    "job_id": str(job.id),
                    "website_url": job.website_url,
                    "status": QueueJobStatus.FAILED.value,
                    "error": str(exc),
                },
            )
        except Exception as exc:
            error_trace = traceback.format_exc()
            will_retry = job.retry_count + 1 < job.max_retries
            self._mark_failure(
                job.id,
                error_message=str(exc),
                error_trace=error_trace,
                will_retry=will_retry,
                batch_id=job.batch_id,
            )
            status = (
                QueueJobStatus.RETRYING.value if will_retry else QueueJobStatus.FAILED.value
            )
            logger.error(
                "Queue job failed",
                extra={
                    "worker_id": self.worker_id,
                    "job_id": str(job.id),
                    "website_url": job.website_url,
                    "retry_count": job.retry_count + 1,
                    "status": status,
                    "error_trace": error_trace,
                },
            )
        finally:
            job_id_ctx.set(None)
            audit_id_ctx.set(None)

    def _mark_success(
        self,
        job_id: uuid.UUID,
        *,
        audit_id: uuid.UUID,
        duration_ms: int,
        final_state_json: dict,
        batch_id: uuid.UUID | None,
    ) -> None:
        session = SyncSessionLocal()
        try:
            job_repo = AuditQueueJobRepository(session)
            job_repo.mark_success_sync(
                job_id,
                audit_id=audit_id,
                duration_ms=duration_ms,
                final_state_json=final_state_json,
            )
            session.commit()
            if batch_id:
                self.queue_manager.update_batch_status(batch_id)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _mark_failure(
        self,
        job_id: uuid.UUID,
        *,
        error_message: str,
        error_trace: str,
        will_retry: bool,
        batch_id: uuid.UUID | None,
    ) -> None:
        session = SyncSessionLocal()
        try:
            job_repo = AuditQueueJobRepository(session)
            job_repo.mark_failure_sync(
                job_id,
                error_message=error_message,
                error_trace=error_trace,
                will_retry=will_retry,
            )
            session.commit()
            if batch_id:
                self.queue_manager.update_batch_status(batch_id)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def worker_process_main(
    worker_id: str,
    stop_event: Any,
    batch_id: str | None = None,
) -> None:
    """Entry point for multiprocessing worker processes."""
    from app.core.config import get_settings
    from app.core.logging import setup_logging

    settings = get_settings()
    setup_logging(settings.log_level)
    parsed_batch_id = uuid.UUID(batch_id) if batch_id else None
    QueueWorker(
        worker_id,
        settings=settings,
        stop_event=stop_event,
        batch_id=parsed_batch_id,
    ).run()
