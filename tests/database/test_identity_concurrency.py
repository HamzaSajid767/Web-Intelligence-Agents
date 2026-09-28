"""Concurrent claim/rebase should not leave conflicting unique identities."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from app.core.constants import AuditStatus
from app.database.repositories import WebsiteAuditRepository


def test_concurrent_rebase_merge_leaves_single_winner():
    """Second rebase that hits DuplicateKeyError merges into the canonical owner."""
    user_id = uuid4()
    orphan_id = uuid4()
    winner_id = uuid4()
    orphan = {
        "_id": str(orphan_id),
        "user_id": str(user_id),
        "website_url": "https://hayes-cpa.com/",
        "status": AuditStatus.PENDING.value,
        "emails": [],
        "phone_numbers": [],
        "social_links": [],
        "pages": [],
        "pain_points": [],
        "recommendations": [],
        "audit_runs": [{"id": str(uuid4()), "status": "running"}],
        "agent_logs": [],
        "submitted_urls": ["https://hayes-cpa.com/"],
    }
    winner = {
        **orphan,
        "_id": str(winner_id),
        "website_url": "https://hayes.cpa/",
        "submitted_urls": ["https://hayes.cpa/"],
        "audit_runs": [{"id": str(uuid4()), "status": "completed"}],
    }

    collection = MagicMock()
    # Thread A rename succeeds; Thread B hits dup and merges.
    state = {"renamed": False}

    def update_one(filter_doc, update_doc, **_kwargs):
        if "$set" in update_doc and update_doc["$set"].get("website_url") == "https://hayes.cpa/":
            if not state["renamed"]:
                state["renamed"] = True
                return MagicMock()
            raise DuplicateKeyError("E11000")
        return MagicMock()

    def find_one(filter_doc, *args, **kwargs):
        if filter_doc.get("_id") == str(orphan_id):
            return orphan
        if filter_doc.get("website_url") == "https://hayes.cpa/":
            return winner
        return None

    collection.find_one.side_effect = find_one
    collection.update_one.side_effect = update_one
    collection.delete_one.return_value = MagicMock()

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    def rebase():
        return repo.rebase_audit_to_canonical_sync(
            orphan_id,
            "https://hayes.cpa/",
            submitted_url="https://hayes-cpa.com/",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rebase(), range(2)))

    assert set(results) <= {orphan_id, winner_id}
    assert state["renamed"] is True
