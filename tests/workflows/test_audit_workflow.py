"""Audit workflow persistence tests."""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.core.constants import AgentName, AuditStatus
from app.core.exceptions import InvalidSiteError
from app.workflows.audit_workflow import AuditWorkflow


def _healthy_state(agent: str, logs: list[dict]) -> dict:
    return {
        "current_agent": agent,
        "agent_logs": logs,
        "status": AuditStatus.AWAITING_REVIEW.value,
        "crawl_data": {
            "pages": [{"url": "https://example.com", "clean_text": "x" * 200, "success": True}],
            "site_validity": {"is_valid": True},
        },
        "business_profile": {"industry": "Technology", "confidence": 0.8},
        "pain_points": [{"check": "missing_title", "description": "Missing title"}],
        "recommendations": [],
        "email_draft": {"subject": "Hi", "body": "Body"},
        "scores": {"Overall": 50},
    }


@pytest.mark.asyncio
async def test_execute_persists_after_each_node():
    """Workflow should call _persist_node after each graph step and hydrate root."""
    audit_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workflow = AuditWorkflow()

    states = [
        {
            **_healthy_state(AgentName.CRAWLER.value, [{"agent_name": "crawler"}]),
            "status": AuditStatus.RUNNING.value,
        },
        _healthy_state(
            AgentName.BUSINESS_ANALYSIS.value,
            [{"agent_name": "crawler"}, {"agent_name": "business_analysis"}],
        ),
    ]

    async def fake_astream(_initial, stream_mode="values"):
        for state in states:
            yield state

    mock_graph = MagicMock()
    mock_graph.astream = fake_astream

    with (
        patch("app.workflows.audit_workflow.build_audit_graph", return_value=mock_graph),
        patch("app.workflows.audit_workflow.SyncSessionLocal") as mock_session_local,
        patch.object(workflow, "_persist_node") as mock_persist,
    ):
        session = MagicMock()
        mock_session_local.return_value = session

        audit_repo = MagicMock()
        run_repo = MagicMock()
        with patch("app.workflows.audit_workflow.AuditRunRepository", return_value=run_repo):
            with patch("app.workflows.audit_workflow.WebsiteAuditRepository", return_value=audit_repo):
                result = await workflow.execute(audit_id, "https://example.com", run_id)

    assert mock_persist.call_count == 2
    audit_repo.hydrate_from_state_sync.assert_called()
    run_repo.mark_completed_sync.assert_called_once_with(run_id)
    assert result["current_agent"] == AgentName.BUSINESS_ANALYSIS.value


@pytest.mark.asyncio
async def test_reused_workflow_hydrates_both_audits():
    """Sticky persistence gates must reset so a second audit still hydrates."""
    workflow = AuditWorkflow()
    audit_a = uuid.uuid4()
    audit_b = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()

    async def fake_astream(_initial, stream_mode="values"):
        yield _healthy_state(AgentName.HUMAN_REVIEW.value, [{"agent_name": "reviewer"}])

    mock_graph = MagicMock()
    mock_graph.astream = fake_astream
    hydrations: list[uuid.UUID] = []

    with (
        patch("app.workflows.audit_workflow.build_audit_graph", return_value=mock_graph),
        patch("app.workflows.audit_workflow.SyncSessionLocal") as mock_session_local,
        patch.object(workflow, "_persist_node"),
    ):
        session = MagicMock()
        mock_session_local.return_value = session
        audit_repo = MagicMock()

        def _hydrate(audit_id, state, **kwargs):
            hydrations.append(audit_id)
            return True

        audit_repo.hydrate_from_state_sync.side_effect = _hydrate
        run_repo = MagicMock()
        with patch("app.workflows.audit_workflow.AuditRunRepository", return_value=run_repo):
            with patch("app.workflows.audit_workflow.WebsiteAuditRepository", return_value=audit_repo):
                first = await workflow.execute(audit_a, "https://a.example", run_a)
                second = await workflow.execute(audit_b, "https://b.example", run_b)

    assert hydrations == [audit_a, audit_b]
    assert first["status"] == AuditStatus.AWAITING_REVIEW.value
    assert second["status"] == AuditStatus.AWAITING_REVIEW.value
    assert first["crawl_data"]["pages"]
    assert second["crawl_data"]["pages"]


@pytest.mark.asyncio
async def test_invalid_site_raises_after_hydrate():
    audit_id = uuid.uuid4()
    run_id = uuid.uuid4()
    workflow = AuditWorkflow()

    async def fake_astream(_initial, stream_mode="values"):
        yield {
            "current_agent": AgentName.CRAWLER.value,
            "agent_logs": [{"agent_name": "crawler"}],
            "status": AuditStatus.INVALID_SITE.value,
            "error": "Parked domain",
            "crawl_data": {
                "pages": [{"url": "https://parked.test", "clean_text": "for sale", "success": True}],
                "site_validity": {"is_valid": False, "reason": "Parked domain"},
            },
            "business_profile": {},
            "pain_points": [],
            "recommendations": [],
            "email_draft": {},
        }

    mock_graph = MagicMock()
    mock_graph.astream = fake_astream

    with (
        patch("app.workflows.audit_workflow.build_audit_graph", return_value=mock_graph),
        patch("app.workflows.audit_workflow.SyncSessionLocal") as mock_session_local,
        patch.object(workflow, "_persist_node"),
    ):
        session = MagicMock()
        mock_session_local.return_value = session
        audit_repo = MagicMock()
        run_repo = MagicMock()
        with patch("app.workflows.audit_workflow.AuditRunRepository", return_value=run_repo):
            with patch("app.workflows.audit_workflow.WebsiteAuditRepository", return_value=audit_repo):
                with pytest.raises(InvalidSiteError, match="Parked domain"):
                    await workflow.execute(audit_id, "https://parked.test", run_id)

    audit_repo.hydrate_from_state_sync.assert_called_once()
    run_repo.mark_failed_sync.assert_called_once()
    run_repo.mark_completed_sync.assert_not_called()
