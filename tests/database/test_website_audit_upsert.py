"""Tests for website_audits claim-or-create (formerly upsert-by-URL)."""

from unittest.mock import MagicMock
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core.constants import AuditStatus
from app.database.models import WebsiteAudit
from app.database.repositories import WebsiteAuditRepository


def test_claim_or_create_inserts_when_missing():
    user_id = uuid4()
    audit_id = uuid4()
    url = "https://example.com/"
    doc = {
        "_id": str(audit_id),
        "user_id": str(user_id),
        "website_url": url,
        "status": AuditStatus.PENDING.value,
        "emails": [],
        "phone_numbers": [],
        "social_links": [],
        "pages": [],
        "pain_points": [],
        "recommendations": [],
        "audit_runs": [],
        "agent_logs": [],
        "submitted_urls": [url],
    }

    collection = MagicMock()
    collection.find_one.return_value = None
    collection.find_one_and_update.return_value = doc

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    result = repo.upsert_by_website_url_sync(user_id=user_id, website_url=url)

    assert isinstance(result, WebsiteAudit)
    assert result.id == audit_id
    assert result.website_url == url
    collection.find_one_and_update.assert_called_once()
    args, kwargs = collection.find_one_and_update.call_args
    assert args[0] == {"website_url": url}
    assert "$setOnInsert" in args[1]
    assert "$set" in args[1]
    assert args[1]["$set"]["status"] == AuditStatus.PENDING.value
    assert args[1]["$set"]["pages"] == []
    assert kwargs["upsert"] is True
    assert kwargs["return_document"] == ReturnDocument.AFTER


def test_claim_or_create_retries_on_duplicate_key():
    user_id = uuid4()
    audit_id = uuid4()
    url = "https://example.com/"
    doc = {
        "_id": str(audit_id),
        "user_id": str(user_id),
        "website_url": url,
        "status": AuditStatus.PENDING.value,
        "emails": [],
        "phone_numbers": [],
        "social_links": [],
        "pages": [],
        "pain_points": [],
        "recommendations": [],
        "audit_runs": [{"id": str(uuid4()), "status": "completed"}],
        "agent_logs": [],
        "submitted_urls": [url],
    }

    collection = MagicMock()
    collection.find_one.return_value = None
    collection.find_one_and_update.side_effect = [
        DuplicateKeyError("E11000"),
        doc,
    ]

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    result = repo.upsert_by_website_url_sync(user_id=user_id, website_url=url)

    assert result.id == audit_id
    assert len(collection.find_one_and_update.call_args_list) == 2
    second_args, second_kwargs = collection.find_one_and_update.call_args_list[1]
    assert "$set" in second_args[1]
    assert "$setOnInsert" not in second_args[1]
    assert second_kwargs.get("upsert") is not True
