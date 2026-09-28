"""Tests for queue worker behavior."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.core.constants import QueueJobStatus
from app.queue.worker import QueueWorker


def _stop_event():
    event = MagicMock()
    event.is_set.return_value = False
    return event


def test_worker_marks_success_on_completed_audit():
    job = MagicMock()
    job.id = uuid4()
    job.website_url = "https://example.com"
    job.retry_count = 0
    job.batch_id = uuid4()

    worker = QueueWorker("worker-1", stop_event=_stop_event())
    worker._claim_next_job = MagicMock(side_effect=[job, None])
    worker._has_pending_jobs = MagicMock(return_value=False)
    worker.audit_runner.run = MagicMock(
        return_value=MagicMock(
            audit_id=uuid4(),
            duration_ms=1200,
            final_state={"status": "awaiting_review"},
        ),
    )
    worker._mark_success = MagicMock()
    worker._mark_failure = MagicMock()

    worker.run()

    worker._mark_success.assert_called_once()
    worker._mark_failure.assert_not_called()


def test_worker_marks_failure_and_continues_on_error():
    job = MagicMock()
    job.id = uuid4()
    job.website_url = "https://example.com"
    job.retry_count = 0
    job.max_retries = 3
    job.batch_id = None

    worker = QueueWorker("worker-1", stop_event=_stop_event())
    worker._claim_next_job = MagicMock(side_effect=[job, None])
    worker._has_pending_jobs = MagicMock(return_value=False)
    worker.audit_runner.run = MagicMock(side_effect=RuntimeError("boom"))
    worker._mark_success = MagicMock()
    worker._mark_failure = MagicMock()

    worker.run()

    worker._mark_failure.assert_called_once()
    kwargs = worker._mark_failure.call_args.kwargs
    assert kwargs["will_retry"] is True
    assert kwargs["error_message"] == "boom"


def test_worker_marks_failed_when_retries_exhausted():
    job = MagicMock()
    job.id = uuid4()
    job.website_url = "https://example.com"
    job.retry_count = 2
    job.max_retries = 3
    job.batch_id = None

    worker = QueueWorker("worker-1", stop_event=_stop_event())
    worker._claim_next_job = MagicMock(side_effect=[job, None])
    worker._has_pending_jobs = MagicMock(return_value=False)
    worker.audit_runner.run = MagicMock(side_effect=RuntimeError("boom"))
    worker._mark_failure = MagicMock()

    worker.run()

    kwargs = worker._mark_failure.call_args.kwargs
    assert kwargs["will_retry"] is False


def test_worker_marks_invalid_site_failed_without_retry():
    from app.core.exceptions import InvalidSiteError

    job = MagicMock()
    job.id = uuid4()
    job.website_url = "https://parked.example"
    job.retry_count = 0
    job.max_retries = 3
    job.batch_id = None

    worker = QueueWorker("worker-1", stop_event=_stop_event())
    worker._claim_next_job = MagicMock(side_effect=[job, None])
    worker._has_pending_jobs = MagicMock(return_value=False)
    worker.audit_runner.run = MagicMock(
        side_effect=InvalidSiteError("Parked domain", audit_id=uuid4())
    )
    worker._mark_success = MagicMock()
    worker._mark_failure = MagicMock()

    worker.run()

    worker._mark_success.assert_not_called()
    worker._mark_failure.assert_called_once()
    assert worker._mark_failure.call_args.kwargs["will_retry"] is False
    assert "Parked domain" in worker._mark_failure.call_args.kwargs["error_message"]


def test_serialize_audit_state_strips_raw_html():
    from app.utils.audit_state import serialize_audit_state

    state = {
        "crawl_data": {
            "pages": [{"url": "https://example.com", "raw_html": "<html></html>"}],
        },
    }
    serialized = serialize_audit_state(state)
    assert "raw_html" not in serialized["crawl_data"]["pages"][0]
