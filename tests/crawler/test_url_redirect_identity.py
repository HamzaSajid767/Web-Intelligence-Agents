"""Crawler redirect / canonical identity tests."""

import pytest

from app.crawler.crawler_service import CrawlerService
from app.crawler.models import CrawlSession, PageFetchResult


class _RedirectManager:
    def __init__(self, final_url: str, html: str = "<html><head></head><body>Home</body></html>"):
        self.final_url = final_url
        self.html = html

    async def fetch_page(self, url: str, session: CrawlSession | None = None) -> PageFetchResult:
        return PageFetchResult(
            url=self.final_url,
            status_code=200,
            success=True,
            html=self.html,
            text="Home",
            backend_used="http",
            metadata={"canonical": self.final_url} if "canonical" in self.html else {},
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_crawl_sets_submitted_final_and_canonical_on_redirect():
    html = (
        '<html><head><link rel="canonical" href="https://hayes.cpa/"></head>'
        "<body>Hayes CPA</body></html>"
    )
    service = CrawlerService(
        manager=_RedirectManager("https://hayes.cpa/", html=html),  # type: ignore[arg-type]
    )
    service.max_pages = 1

    result = await service.crawl("https://hayes-cpa.com")

    assert result.submitted_url == "https://hayes-cpa.com/"
    assert result.final_url == "https://hayes.cpa/"
    assert result.canonical_url == "https://hayes.cpa/"
    assert result.canonical_website_url == "https://hayes.cpa/"
    assert result.redirect_history
    assert result.redirect_history[0]["from"] == "https://hayes-cpa.com/"
    assert result.redirect_history[0]["to"] == "https://hayes.cpa/"

    state = service.to_state_dict(result)
    assert state["submitted_url"] == "https://hayes-cpa.com/"
    assert state["canonical_url"] == "https://hayes.cpa/"
    assert state["final_url"] == "https://hayes.cpa/"
