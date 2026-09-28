"""Tests for AuditRunner."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.agents.state import AuditState
from app.services.audit_runner import AuditRunner, AuditRunResult


def test_audit_runner_creates_records_and_returns_result():
    audit_id = uuid4()
    run_id = uuid4()
    user_id = uuid4()

    mock_workflow = MagicMock()
    mock_workflow.execute_sync.return_value = AuditState(
        audit_id=str(audit_id),
        website_url="https://example.com/",
        status="awaiting_review",
    )

    mock_session = MagicMock()
    mock_session.is_active = True
    mock_user = MagicMock(id=user_id)
    mock_audit = MagicMock(id=audit_id)
    mock_run = MagicMock(id=run_id)

    with (
        patch("app.services.audit_runner.SyncSessionLocal", return_value=mock_session),
        patch.object(AuditRunner, "get_or_create_default_user", return_value=mock_user),
        patch("app.services.audit_runner.WebsiteAuditRepository") as audit_repo_cls,
        patch("app.services.audit_runner.AuditRunRepository") as run_repo_cls,
        patch("app.services.audit_runner.time.perf_counter", side_effect=[0.0, 1.5]),
    ):
        audit_repo_cls.return_value.claim_or_create_by_url_sync.return_value = mock_audit
        run_repo_cls.return_value.create_sync.return_value = mock_run
        result = AuditRunner(workflow=mock_workflow).run("https://example.com/")

    assert isinstance(result, AuditRunResult)
    assert result.audit_id == audit_id
    assert result.run_id == run_id
    assert result.website_url == "https://example.com/"
    assert result.duration_ms == 1500
    audit_repo_cls.return_value.claim_or_create_by_url_sync.assert_called_once_with(
        user_id=user_id,
        submitted_url="https://example.com/",
    )
    mock_workflow.execute_sync.assert_called_once_with(audit_id, "https://example.com/", run_id)
    mock_session.commit.assert_called_once()
    mock_session.close.assert_called()
