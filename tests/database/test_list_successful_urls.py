"""Tests for listing successful website audit URLs (alias-aware)."""

from unittest.mock import MagicMock

from app.core.constants import AuditStatus
from app.database.repositories import WebsiteAuditRepository


def test_list_successful_urls_sync_queries_completed_without_errors():
    collection = MagicMock()
    collection.find.return_value = [
        {"website_url": "https://ok.com/", "submitted_urls": ["https://ok.com/"]},
        {
            "website_url": "https://review.com/",
            "submitted_urls": ["https://review.com/"],
        },
    ]

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    found = repo.list_successful_urls_sync(
        ["https://ok.com/", "https://fail.com/", "https://review.com/"],
    )

    assert found == {"https://ok.com/", "https://review.com/"}
    collection.find.assert_called_once()
    query = collection.find.call_args[0][0]
    assert "$or" in query
    assert set(query["status"]["$in"]) == {
        AuditStatus.COMPLETED.value,
        AuditStatus.AWAITING_REVIEW.value,
    }
    assert query["pages.0"] == {"$exists": True}
    and_clauses = query["$and"]
    assert {"error_message": None} in and_clauses[0]["$or"]
    assert {"metadata.crawl_errors": []} in and_clauses[1]["$or"]


def test_list_successful_urls_matches_via_alias():
    collection = MagicMock()
    collection.find.return_value = [
        {
            "website_url": "https://hayes.cpa/",
            "submitted_urls": ["https://hayes.cpa/", "https://hayes-cpa.com/"],
        },
    ]

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    found = repo.list_successful_urls_sync(["https://hayes-cpa.com/"])
    assert found == {"https://hayes-cpa.com/"}


def test_list_successful_urls_sync_chunks_large_lists():
    collection = MagicMock()
    collection.find.return_value = []

    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    repo.db.website_audits = collection

    urls = [f"https://site{i}.com/" for i in range(3)]
    # lookup_keys expands each URL; tiny chunk forces multiple queries
    found = repo.list_successful_urls_sync(urls, chunk_size=2)

    assert found == set()
    assert collection.find.call_count >= 2


def test_list_successful_urls_sync_empty_input():
    repo = WebsiteAuditRepository(MagicMock())
    repo.db = MagicMock()
    assert repo.list_successful_urls_sync([]) == set()
    repo.db.website_audits.find.assert_not_called()
