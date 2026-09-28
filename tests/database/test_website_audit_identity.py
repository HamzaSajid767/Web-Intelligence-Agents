"""Tests for canonical WebsiteAudit claim, rebase, merge, and hydrate."""

from unittest.mock import MagicMock
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.core.constants import AuditStatus
from app.database.repositories import WebsiteAuditRepository


def _doc(*, audit_id, user_id, website_url, submitted_urls=None, audit_runs=None):
    return {
        "_id": str(audit_id),
        "user_id": str(user_id),
        "website_url": website_url,
        "status": AuditStatus.PENDING.value,
        "emails": [],
        "phone_numbers": [],
        "social_links": [],
        "pages": [],
        "pain_points": [],
        "recommendations": [],
        "audit_runs": audit_runs or [],
        "agent_logs": [],
        "submitted_urls": submitted_urls or [website_url],
        "latest_submitted_url": website_url,
        "redirect_history": [],
    }


def test_claim_or_create_finds_by_alias_after_canonical_rename():
    user_id = uuid4()
    audit_id = uuid4()
    existing = _doc(
        audit_id=audit_id,
        user_id=user_id,
        website_url="https://hayes.cpa/",
        submitted_urls=["https://hayes.cpa/", "https://hayes-cpa.com/"],
    )
    updated = {**existing, "status": AuditStatus.PENDING.value}

    collection = MagicMock()
    collection.find_one.return_value = existing
    collection.find_one_and_update.return_value = updated

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    result = repo.claim_or_create_by_url_sync(
        user_id=user_id,
        submitted_url="https://hayes-cpa.com",
    )

    assert result.id == audit_id
    assert result.website_url == "https://hayes.cpa/"
    collection.find_one.assert_called_once()
    # Should update existing, not insert via website_url exact upsert.
    args, _kwargs = collection.find_one_and_update.call_args
    assert args[0] == {"_id": str(audit_id)}


def test_rebase_to_canonical_updates_identity_without_conflict():
    user_id = uuid4()
    audit_id = uuid4()
    current = _doc(
        audit_id=audit_id,
        user_id=user_id,
        website_url="https://hayes-cpa.com/",
    )
    collection = MagicMock()
    collection.find_one.return_value = current
    collection.update_one.return_value = MagicMock()

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    surviving = repo.rebase_audit_to_canonical_sync(
        audit_id,
        "https://hayes.cpa/",
        submitted_url="https://hayes-cpa.com/",
        final_url="https://hayes.cpa/",
        redirect_history=[{"from": "https://hayes-cpa.com/", "to": "https://hayes.cpa/"}],
    )

    assert surviving == audit_id
    args, _kwargs = collection.update_one.call_args
    assert args[0] == {"_id": str(audit_id)}
    assert args[1]["$set"]["website_url"] == "https://hayes.cpa/"
    assert "submitted_urls" in args[1]["$addToSet"]


def test_rebase_merges_into_existing_canonical_owner():
    user_id = uuid4()
    orphan_id = uuid4()
    winner_id = uuid4()
    run_id = uuid4()
    orphan = _doc(
        audit_id=orphan_id,
        user_id=user_id,
        website_url="https://hayes-cpa.com/",
        audit_runs=[{"id": str(run_id), "status": "running"}],
    )
    winner = _doc(
        audit_id=winner_id,
        user_id=user_id,
        website_url="https://hayes.cpa/",
        audit_runs=[{"id": str(uuid4()), "status": "completed"}],
    )

    collection = MagicMock()
    # first find_one: current orphan; merge path find_one: winner then fresh orphan
    collection.find_one.side_effect = [orphan, winner, orphan]
    collection.update_one.side_effect = [
        DuplicateKeyError("E11000"),
        MagicMock(),  # winner update
    ]
    collection.delete_one.return_value = MagicMock()

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    surviving = repo.rebase_audit_to_canonical_sync(
        orphan_id,
        "https://hayes.cpa/",
        submitted_url="https://hayes-cpa.com/",
        final_url="https://hayes.cpa/",
    )

    assert surviving == winner_id
    collection.delete_one.assert_called_once_with({"_id": str(orphan_id)})
    merge_update = collection.update_one.call_args_list[1][0][1]
    assert "$push" in merge_update
    assert merge_update["$push"]["audit_runs"]["$each"][0]["id"] == str(run_id)


def test_hydrate_does_not_mutate_website_url():
    audit_id = uuid4()
    collection = MagicMock()
    collection.find_one.return_value = {"metadata": {}}

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    repo.hydrate_from_state_sync(
        audit_id,
        {
            "status": AuditStatus.AWAITING_REVIEW.value,
            "crawl_data": {
                "canonical_website_url": "https://hayes.cpa/",
                "canonical_url": "https://hayes.cpa/",
                "final_url": "https://hayes.cpa/",
                "pages": [{"url": "https://hayes.cpa/", "title": "Home"}],
                "contacts": {},
            },
            "pain_points": [],
            "recommendations": [],
            "email_draft": {},
            "scores": {},
        },
    )

    set_fields = collection.update_one.call_args[0][1]["$set"]
    assert "website_url" not in set_fields
    assert set_fields["final_url"] == "https://hayes.cpa/"
