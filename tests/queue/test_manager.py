"""Tests for queue manager."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.core.constants import QueueBatchStatus, QueueJobStatus
from app.queue.manager import QueueManager


def test_enqueue_urls_dedupes_and_creates_batch():
    manager = QueueManager()
    batch_id = uuid4()
    mock_batch = MagicMock(id=batch_id)
    mock_session = MagicMock()

    with (
        patch("app.queue.manager.ensure_indexes_sync"),
        patch("app.queue.manager.SyncSessionLocal", return_value=mock_session),
        patch("app.queue.manager.AuditQueueBatchRepository") as batch_repo_cls,
        patch("app.queue.manager.AuditQueueJobRepository") as job_repo_cls,
        patch("app.queue.manager.WebsiteAuditRepository") as audit_repo_cls,
    ):
        batch_repo = batch_repo_cls.return_value
        job_repo = job_repo_cls.return_value
        batch_repo.create_sync.return_value = mock_batch
        audit_repo_cls.return_value.list_successful_urls_sync.return_value = set()

        result = manager.enqueue_urls(
            [
                "https://example.com",
                "https://example.com/",
                "https://other.com",
            ],
            batch_name="test-batch",
        )

    assert result.batch_id == batch_id
    assert result.enqueued == 2
    assert result.skipped == 0
    batch_repo.create_sync.assert_called_once()
    assert batch_repo.create_sync.call_args.kwargs["total_jobs"] == 2
    job_repo.bulk_create_sync.assert_called_once()
    jobs = job_repo.bulk_create_sync.call_args[0][0]
    assert len(jobs) == 2
    assert jobs[0].website_url == "https://example.com/"
    assert jobs[0].status == QueueJobStatus.QUEUED.value
    batch_repo.update_status_sync.assert_called_once_with(batch_id, QueueBatchStatus.PENDING)
    mock_session.commit.assert_called()


def test_enqueue_urls_dedupes_www_and_apex():
    manager = QueueManager()
    batch_id = uuid4()
    mock_batch = MagicMock(id=batch_id)

    with (
        patch("app.queue.manager.ensure_indexes_sync"),
        patch("app.queue.manager.SyncSessionLocal", return_value=MagicMock()),
        patch("app.queue.manager.AuditQueueBatchRepository") as batch_repo_cls,
        patch("app.queue.manager.AuditQueueJobRepository") as job_repo_cls,
        patch("app.queue.manager.WebsiteAuditRepository") as audit_repo_cls,
    ):
        batch_repo_cls.return_value.create_sync.return_value = mock_batch
        audit_repo_cls.return_value.list_successful_urls_sync.return_value = set()

        result = manager.enqueue_urls(
            [
                "https://www.example.com",
                "https://example.com",
            ],
        )

    assert result.enqueued == 1
    jobs = job_repo_cls.return_value.bulk_create_sync.call_args[0][0]
    assert len(jobs) == 1
    assert jobs[0].website_url in {"https://www.example.com/", "https://example.com/"}


def test_enqueue_urls_skips_successful_audits():
    manager = QueueManager()
    batch_id = uuid4()
    mock_batch = MagicMock(id=batch_id)
    mock_session = MagicMock()

    with (
        patch("app.queue.manager.ensure_indexes_sync"),
        patch("app.queue.manager.SyncSessionLocal", return_value=mock_session),
        patch("app.queue.manager.AuditQueueBatchRepository") as batch_repo_cls,
        patch("app.queue.manager.AuditQueueJobRepository") as job_repo_cls,
        patch("app.queue.manager.WebsiteAuditRepository") as audit_repo_cls,
    ):
        batch_repo_cls.return_value.create_sync.return_value = mock_batch
        audit_repo_cls.return_value.list_successful_urls_sync.return_value = {
            "https://example.com/",
        }

        result = manager.enqueue_urls(
            [
                "https://example.com",
                "https://failed.com",
            ],
        )

    assert result.batch_id == batch_id
    assert result.enqueued == 1
    assert result.skipped == 1
    jobs = job_repo_cls.return_value.bulk_create_sync.call_args[0][0]
    assert len(jobs) == 1
    assert jobs[0].website_url == "https://failed.com/"
    batch_repo_cls.return_value.create_sync.assert_called_once()
    assert batch_repo_cls.return_value.create_sync.call_args.kwargs["total_jobs"] == 1


def test_enqueue_urls_still_enqueues_failed_audits():
    """Failed audits are not returned by list_successful_urls_sync, so they enqueue."""
    manager = QueueManager()
    batch_id = uuid4()
    mock_batch = MagicMock(id=batch_id)

    with (
        patch("app.queue.manager.ensure_indexes_sync"),
        patch("app.queue.manager.SyncSessionLocal", return_value=MagicMock()),
        patch("app.queue.manager.AuditQueueBatchRepository") as batch_repo_cls,
        patch("app.queue.manager.AuditQueueJobRepository") as job_repo_cls,
        patch("app.queue.manager.WebsiteAuditRepository") as audit_repo_cls,
    ):
        batch_repo_cls.return_value.create_sync.return_value = mock_batch
        audit_repo_cls.return_value.list_successful_urls_sync.return_value = set()

        result = manager.enqueue_urls(["https://failed.com"])

    assert result.enqueued == 1
    assert result.skipped == 0
    jobs = job_repo_cls.return_value.bulk_create_sync.call_args[0][0]
    assert jobs[0].website_url == "https://failed.com/"


def test_enqueue_urls_force_bypasses_successful_skip():
    manager = QueueManager()
    batch_id = uuid4()
    mock_batch = MagicMock(id=batch_id)

    with (
        patch("app.queue.manager.ensure_indexes_sync"),
        patch("app.queue.manager.SyncSessionLocal", return_value=MagicMock()),
        patch("app.queue.manager.AuditQueueBatchRepository") as batch_repo_cls,
        patch("app.queue.manager.AuditQueueJobRepository") as job_repo_cls,
        patch("app.queue.manager.WebsiteAuditRepository") as audit_repo_cls,
    ):
        batch_repo_cls.return_value.create_sync.return_value = mock_batch

        result = manager.enqueue_urls(
            ["https://example.com"],
            force=True,
        )

    assert result.enqueued == 1
    assert result.skipped == 0
    audit_repo_cls.return_value.list_successful_urls_sync.assert_not_called()
    jobs = job_repo_cls.return_value.bulk_create_sync.call_args[0][0]
    assert jobs[0].website_url == "https://example.com/"


def test_enqueue_urls_all_skipped_raises():
    manager = QueueManager()

    with (
        patch("app.queue.manager.ensure_indexes_sync"),
        patch("app.queue.manager.SyncSessionLocal", return_value=MagicMock()),
        patch("app.queue.manager.AuditQueueBatchRepository") as batch_repo_cls,
        patch("app.queue.manager.WebsiteAuditRepository") as audit_repo_cls,
    ):
        audit_repo_cls.return_value.list_successful_urls_sync.return_value = {
            "https://example.com/",
            "https://other.com/",
        }

        with pytest.raises(ValueError, match="already have successful audits"):
            manager.enqueue_urls(
                ["https://example.com", "https://other.com"],
            )

    batch_repo_cls.return_value.create_sync.assert_not_called()


def test_enqueue_urls_rejects_empty_list():
    manager = QueueManager()
    with pytest.raises(ValueError, match="No valid URLs"):
        manager.enqueue_urls([])


def test_get_batch_progress_returns_counts():
    manager = QueueManager()
    batch_id = uuid4()
    mock_session = MagicMock()
    mock_batch = MagicMock(id=batch_id, status=QueueBatchStatus.RUNNING.value, total_jobs=3)

    with (
        patch("app.queue.manager.SyncSessionLocal", return_value=mock_session),
        patch("app.queue.manager.AuditQueueBatchRepository") as batch_repo_cls,
        patch("app.queue.manager.AuditQueueJobRepository") as job_repo_cls,
    ):
        batch_repo_cls.return_value.get_by_id_sync.return_value = mock_batch
        job_repo_cls.return_value.count_by_status_sync.return_value = {
            QueueJobStatus.SUCCESS.value: 2,
            QueueJobStatus.QUEUED.value: 1,
        }
        progress = manager.get_batch_progress(batch_id)

    assert progress["batch_id"] == str(batch_id)
    assert progress["completed"] == 2
    assert progress["pending"] == 1
