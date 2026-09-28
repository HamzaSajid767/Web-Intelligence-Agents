"""CrawlerService parallel crawl tests."""

from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.crawler.crawler_service import CrawlerService
from app.crawler.models import BackendName, PageFetchResult


@pytest.mark.asyncio
async def test_parallel_crawl_respects_max_pages() -> None:
    settings = Settings.model_construct(crawler_max_pages=3, crawler_concurrency=3)
    manager = AsyncMock()
    manager.aclose = AsyncMock()

    html = "<html><head><title>OK</title></head><body>" + ("word " * 200) + "</body></html>"

    async def fake_fetch(url: str, session=None) -> PageFetchResult:
        links = []
        if url.rstrip("/").endswith("example.com"):
            links = [
                {"url": "https://example.com/a", "type": "internal"},
                {"url": "https://example.com/b", "type": "internal"},
                {"url": "https://example.com/c", "type": "internal"},
            ]
        return PageFetchResult(
            url=url,
            status_code=200,
            success=True,
            html=html,
            text="word " * 50,
            title="OK",
            links=links,
            backend_used=BackendName.COLLY,
            content_type="text/html",
            response_time_ms=10.0,
        )

    manager.fetch_page = AsyncMock(side_effect=fake_fetch)
    service = CrawlerService(settings=settings, manager=manager)
    result = await service.crawl("https://example.com")

    assert result.total_pages == 3
    assert len(result.pages) == 3
    assert manager.fetch_page.await_count == 3


@pytest.mark.asyncio
async def test_crawl_prioritizes_contact_pages() -> None:
    """Contact URLs should be crawled before shop noise when max_pages is tight."""
    settings = Settings.model_construct(crawler_max_pages=2, crawler_concurrency=1)
    manager = AsyncMock()
    manager.aclose = AsyncMock()

    html = "<html><head><title>OK</title></head><body>" + ("word " * 200) + "</body></html>"

    async def fake_fetch(url: str, session=None) -> PageFetchResult:
        links = []
        if url.rstrip("/").endswith("example.com"):
            # Shop listed first; contact must still win via prioritization.
            links = [
                {"url": "https://example.com/shop", "text": "Shop", "type": "internal"},
                {"url": "https://example.com/products", "text": "Products", "type": "internal"},
                {"url": "https://example.com/contact", "text": "Contact Us", "type": "internal"},
            ]
        return PageFetchResult(
            url=url,
            status_code=200,
            success=True,
            html=html,
            text="word " * 50,
            title="OK",
            links=links,
            backend_used=BackendName.COLLY,
            content_type="text/html",
            response_time_ms=10.0,
        )

    manager.fetch_page = AsyncMock(side_effect=fake_fetch)
    service = CrawlerService(settings=settings, manager=manager)
    result = await service.crawl("https://example.com")

    crawled = {page.url.rstrip("/") for page in result.pages}
    assert "https://example.com" in crawled
    assert "https://example.com/contact" in crawled
    assert "https://example.com/shop" not in crawled
