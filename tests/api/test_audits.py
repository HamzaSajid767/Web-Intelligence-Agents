"""Audit API route tests."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_audit_service, get_email_service, get_report_service
from app.main import create_app


@pytest.fixture
def client():
    """Test client with mocked services."""
    app = create_app()

    mock_audit_service = MagicMock()
    mock_audit_service.create_audit = AsyncMock(
        return_value=(uuid4(), "pending")
    )

    mock_report_service = MagicMock()
    audit_id = uuid4()
    mock_report_service.get_full_report = AsyncMock(
        return_value={
            "audit_id": str(audit_id),
            "website_url": "https://example.com",
            "status": "completed",
            "error_message": None,
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
            "emails": [],
            "phone_numbers": [],
            "social_links": [],
            "pages": [],
            "business_profile": None,
            "pain_points": [],
            "scores": None,
            "recommendations": [],
            "email": None,
            "agent_logs": [],
            "audit_runs": [],
        }
    )

    mock_email_service = MagicMock()
    mock_email_service.get_email = AsyncMock(
        return_value={
            "audit_id": str(audit_id),
            "email_id": str(uuid4()),
            "subject": "Test Subject",
            "body": "Test Body",
            "status": "draft",
            "approved_at": None,
        }
    )
    mock_email_service.approve_email = AsyncMock(
        return_value={
            "audit_id": str(audit_id),
            "email_id": str(uuid4()),
            "subject": "Test Subject",
            "body": "Test Body",
            "status": "approved",
            "approved_at": "2024-01-01T00:00:00+00:00",
            "message": "Email approved for manual send. No email was sent automatically.",
        }
    )

    app.dependency_overrides[get_audit_service] = lambda: mock_audit_service
    app.dependency_overrides[get_report_service] = lambda: mock_report_service
    app.dependency_overrides[get_email_service] = lambda: mock_email_service

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_health_endpoint(client):
    """Health endpoint should return ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_audit(client):
    """POST /audits should return audit_id."""
    response = client.post("/audits", json={"website_url": "https://example.com"})
    assert response.status_code == 202
    data = response.json()
    assert "audit_id" in data
    assert data["status"] == "pending"


def test_get_audit(client):
    """GET /audits/{id} should return report."""
    audit_id = uuid4()
    response = client.get(f"/audits/{audit_id}")
    assert response.status_code == 200
    assert response.json()["website_url"] == "https://example.com"


def test_get_email(client):
    """GET /audits/{id}/email should return email draft."""
    audit_id = uuid4()
    response = client.get(f"/audits/{audit_id}/email")
    assert response.status_code == 200
    assert response.json()["subject"] == "Test Subject"


def test_approve_email(client):
    """POST /audits/{id}/approve should approve without sending."""
    audit_id = uuid4()
    response = client.post(f"/audits/{audit_id}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert "manual send" in response.json()["message"]
