"""Bulk audit queue manager."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.constants import QueueBatchStatus, QueueJobStatus
from app.core.logging import get_logger
from app.database.indexes import ensure_indexes_sync
from app.database.models import AuditQueueJob
from app.database.repositories import (
    AuditQueueBatchRepository,
    AuditQueueJobRepository,
    WebsiteAuditRepository,
)
from app.database.session import SyncSessionLocal

logger = get_logger(__name__)


@dataclass(frozen=True)
class EnqueueResult:
    """Result of enqueueing URLs into the audit queue."""

    batch_id: uuid.UUID
    enqueued: int
    skipped: int


class QueueManager:
    """Enqueue URLs and track batch progress."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @staticmethod
    def iter_urls_from_file(path: Path) -> Iterator[str]:
        """Stream URLs from a text file, one per line.

        Invalid lines are skipped with a warning so a large file is not aborted
        by a single bad entry.
        """
        from app.services.audit_service import AuditService

        with path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                try:
                    yield AuditService.validate_url(stripped)
                except ValueError as exc:
                    logger.warning(
                        "Skipping invalid URL in file",
                        extra={
                            "path": str(path),
                            "line": line_no,
                            "url": stripped,
                            "error": str(exc),
                        },
                    )

    def enqueue_urls(
        self,
        urls: Iterable[str],
        *,
        batch_name: str | None = None,
        source: str = "cli",
        force: bool = False,
    ) -> EnqueueResult:
        """Validate, dedupe, skip successful audits, and enqueue remaining URLs."""
        from app.core.url_identity import lookup_keys
        from app.services.audit_service import AuditService

        seen_keys: set[str] = set()
        normalized: list[str] = []
        for url in urls:
            valid = AuditService.validate_url(url)
            keys = set(lookup_keys(valid))
            if keys & seen_keys:
                continue
            seen_keys.update(keys)
            normalized.append(valid)

        if not normalized:
            raise ValueError("No valid URLs to enqueue")

        ensure_indexes_sync()
        session = SyncSessionLocal()
        try:
            audit_repo = WebsiteAuditRepository(session)
            skipped = 0
            to_enqueue = normalized
            if not force:
                successful = audit_repo.list_successful_urls_sync(normalized)
                if successful:
                    to_enqueue = [url for url in normalized if url not in successful]
                    skipped = len(normalized) - len(to_enqueue)

            if not to_enqueue:
                raise ValueError(
                    f"All {len(normalized)} URLs already have successful audits; "
                    "use --force to re-scrape",
                )

            batch_repo = AuditQueueBatchRepository(session)
            job_repo = AuditQueueJobRepository(session)
            batch = batch_repo.create_sync(
                name=batch_name,
                source=source,
                total_jobs=len(to_enqueue),
            )
            batch_id = batch.id
            now = datetime.now(UTC)
            chunk: list[AuditQueueJob] = []

            for url in to_enqueue:
                chunk.append(
                    AuditQueueJob(
                        batch_id=batch_id,
                        website_url=url,
                        status=QueueJobStatus.QUEUED.value,
                        retry_count=0,
                        max_retries=self.settings.max_retries,
                        queued_at=now,
                    ),
                )
                if len(chunk) >= self.settings.queue_batch_size:
                    job_repo.bulk_create_sync(chunk)
                    session.commit()
                    chunk.clear()

            if chunk:
                job_repo.bulk_create_sync(chunk)
            batch_repo.update_status_sync(batch_id, QueueBatchStatus.PENDING)
            session.commit()
            logger.info(
                "Enqueued audit batch",
                extra={
                    "batch_id": str(batch_id),
                    "total_jobs": len(to_enqueue),
                    "skipped": skipped,
                    "force": force,
                },
            )
            return EnqueueResult(batch_id=batch_id, enqueued=len(to_enqueue), skipped=skipped)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def enqueue_file(
        self,
        path: Path,
        *,
        batch_name: str | None = None,
        force: bool = False,
    ) -> EnqueueResult:
        """Enqueue URLs from a file without loading all lines into memory."""
        return self.enqueue_urls(
            self.iter_urls_from_file(path),
            batch_name=batch_name or path.name,
            force=force,
        )

    def get_batch_progress(self, batch_id: uuid.UUID) -> dict[str, int | str]:
        """Return job counts by status for a batch."""
        session = SyncSessionLocal()
        try:
            batch_repo = AuditQueueBatchRepository(session)
            job_repo = AuditQueueJobRepository(session)
            batch = batch_repo.get_by_id_sync(batch_id)
            if not batch:
                raise ValueError(f"Batch not found: {batch_id}")
            counts = job_repo.count_by_status_sync(batch_id)
            total = sum(counts.values())
            return {
                "batch_id": str(batch_id),
                "batch_status": batch.status,
                "total_jobs": batch.total_jobs,
                "counts": counts,
                "completed": counts.get(QueueJobStatus.SUCCESS.value, 0)
                + counts.get(QueueJobStatus.FAILED.value, 0),
                "pending": total
                - counts.get(QueueJobStatus.SUCCESS.value, 0)
                - counts.get(QueueJobStatus.FAILED.value, 0),
            }
        finally:
            session.close()

    def recover_stale_jobs(self) -> int:
        """Reclaim jobs stuck in running state."""
        session = SyncSessionLocal()
        try:
            job_repo = AuditQueueJobRepository(session)
            stale_before = datetime.now(UTC) - timedelta(
                seconds=self.settings.queue_stale_job_seconds,
            )
            recovered = job_repo.recover_stale_jobs_sync(stale_before)
            session.commit()
            if recovered:
                logger.warning("Recovered stale queue jobs", extra={"count": recovered})
            return recovered
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def list_unfinished_batches(self) -> list[uuid.UUID]:
        """Return batch IDs that still have pending work."""
        session = SyncSessionLocal()
        try:
            batch_repo = AuditQueueBatchRepository(session)
            job_repo = AuditQueueJobRepository(session)
            batches = batch_repo.list_unfinished_sync()
            unfinished: list[uuid.UUID] = []
            for batch in batches:
                if job_repo.has_pending_jobs_sync(batch.id):
                    unfinished.append(batch.id)
            return unfinished
        finally:
            session.close()

    def update_batch_status(self, batch_id: uuid.UUID) -> None:
        """Recompute batch status from job counts."""
        session = SyncSessionLocal()
        try:
            batch_repo = AuditQueueBatchRepository(session)
            job_repo = AuditQueueJobRepository(session)
            batch = batch_repo.get_by_id_sync(batch_id)
            if not batch:
                return
            counts = job_repo.count_by_status_sync(batch_id)
            pending = counts.get(QueueJobStatus.QUEUED.value, 0) + counts.get(
                QueueJobStatus.RETRYING.value,
                0,
            )
            running = counts.get(QueueJobStatus.RUNNING.value, 0)
            failed = counts.get(QueueJobStatus.FAILED.value, 0)
            success = counts.get(QueueJobStatus.SUCCESS.value, 0)

            if pending > 0 or running > 0:
                batch_repo.update_status_sync(batch_id, QueueBatchStatus.RUNNING)
            elif failed > 0 and success == 0:
                batch_repo.update_status_sync(batch_id, QueueBatchStatus.FAILED)
            else:
                batch_repo.update_status_sync(batch_id, QueueBatchStatus.COMPLETED)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
