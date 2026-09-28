"""Crawler service unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.crawler.crawler_service import CrawlerService
from app.crawler.manager import CrawlerManager
from app.crawler.models import BackendName, MAX_CLEAN_TEXT_LENGTH, PageFetchResult


@pytest.mark.asyncio
async def test_crawl_caps_clean_text() -> None:
    """Crawler should cap clean_text length per page."""
    long_html = f"<html><head><title>Test</title></head><body>{'word ' * 5000}</body></html>"
    fetch_result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html=long_html,
        content_type="text/html",
        backend_used=BackendName.COLLY,
    )

    mock_manager = MagicMock(spec=CrawlerManager)
    mock_manager.fetch_page = AsyncMock(return_value=fetch_result)
    mock_manager.aclose = AsyncMock()

    service = CrawlerService(manager=mock_manager)
    service.max_pages = 1

    result = await service.crawl("https://example.com")

    assert len(result.pages) == 1
    assert len(result.pages[0].clean_text or "") <= MAX_CLEAN_TEXT_LENGTH


@pytest.mark.asyncio
async def test_crawl_delegates_to_manager() -> None:
    """CrawlerService should fetch pages via CrawlerManager."""
    fetch_result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><head><title>Home</title></head><body>Welcome</body></html>",
        content_type="text/html",
        backend_used=BackendName.COLLY,
    )

    mock_manager = MagicMock(spec=CrawlerManager)
    mock_manager.fetch_page = AsyncMock(return_value=fetch_result)
    mock_manager.aclose = AsyncMock()

    service = CrawlerService(manager=mock_manager)
    service.max_pages = 1

    await service.crawl("https://example.com")

    mock_manager.fetch_page.assert_called()
    mock_manager.aclose.assert_called_once()
