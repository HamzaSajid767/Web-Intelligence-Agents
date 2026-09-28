"""Crawler agent unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.nodes.crawler_agent import crawler_handler
from app.crawler.models import CrawlResult


@pytest.mark.asyncio
async def test_crawler_agent_populates_crawl_data(sample_audit_state, agent_deps):
    """Crawler agent should populate crawl_data and analysis."""
    result = await crawler_handler(sample_audit_state, agent_deps)

    assert result["crawl_data"]["total_pages"] == 1
    assert len(result["crawl_data"]["pages"]) == 1
    assert "page_context" in result["crawl_data"]
    assert "contacts" in result["crawl_data"]
    assert set(result["crawl_data"]["contacts"]) == {"emails", "phone_numbers", "social_links"}
    assert "Welcome to our business website." in result["crawl_data"]["page_context"]
    assert "analysis" in result["crawl_data"]
    assert result["crawl_data"]["analysis"]["summary"] == "Test site summary"
    assert result["crawl_data"]["site_validity"]["is_valid"] is True
    assert result["status"] != "invalid_site"
    assert len(result["agent_logs"]) >= 1


@pytest.mark.asyncio
async def test_crawler_agent_raises_when_no_pages(sample_audit_state, agent_deps):
    """Empty crawl must fail the audit instead of continuing to agents."""
    empty = CrawlResult(
        website_url=sample_audit_state["website_url"],
        pages=[],
        total_pages=0,
        errors=["[Errno 11001] getaddrinfo failed"],
    )
    agent_deps.crawler.crawl = AsyncMock(return_value=empty)
    agent_deps.crawler.to_state_dict = MagicMock(
        return_value={
            "website_url": sample_audit_state["website_url"],
            "pages": [],
            "total_pages": 0,
            "errors": empty.errors,
            "summary": "",
        }
    )

    with pytest.raises(RuntimeError, match="no usable pages"):
        await crawler_handler(sample_audit_state, agent_deps)

    assert sample_audit_state["crawl_data"]["total_pages"] == 0
    assert sample_audit_state["crawl_data"]["errors"] == empty.errors
