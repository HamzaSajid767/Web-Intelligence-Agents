"""CrawlerManager orchestration tests."""

from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.crawler.bot_detection import BotProtectionDetector
from app.crawler.manager import CrawlerManager
from app.crawler.models import BackendName, CrawlSession, PageFetchResult


@pytest.fixture
def settings() -> Settings:
    return Settings(
        use_webclaw_fallback=True,
        crawler_max_retries=1,
        crawler_retry_backoff_seconds=0.01,
        crawler_min_html_length=500,
    )


@pytest.mark.asyncio
async def test_colly_success_no_fallback(settings: Settings) -> None:
    primary = AsyncMock()
    fallback = AsyncMock()
    primary.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><head><title>OK</title></head><body>" + ("word " * 200) + "</body></html>",
        backend_used=BackendName.COLLY,
        response_time_ms=50.0,
    )

    manager = CrawlerManager(primary=primary, fallback=fallback, settings=settings)
    result = await manager.fetch_page("https://example.com", CrawlSession())

    assert result.backend_used == BackendName.COLLY
    fallback.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_bot_detection_triggers_webclaw(settings: Settings) -> None:
    primary = AsyncMock()
    fallback = AsyncMock()
    primary.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><body>Checking your browser</body></html>",
        backend_used=BackendName.COLLY,
    )
    fallback.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        markdown="# Extracted",
        text="Extracted",
        backend_used=BackendName.WEBCLAW,
        response_time_ms=300.0,
    )

    manager = CrawlerManager(
        primary=primary,
        fallback=fallback,
        settings=settings,
        detector=BotProtectionDetector(min_html_length=10),
    )
    result = await manager.fetch_page("https://example.com", CrawlSession())

    assert result.backend_used == BackendName.WEBCLAW
    fallback.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_colly_infrastructure_failure_skips_retries(settings: Settings) -> None:
    primary = AsyncMock()
    fallback = AsyncMock()
    primary.fetch.return_value = PageFetchResult(
        url="https://example.com",
        success=False,
        error="Connection refused",
        backend_used=BackendName.COLLY,
    )
    fallback.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><body>" + ("content " * 100) + "</body></html>",
        backend_used=BackendName.WEBCLAW,
        response_time_ms=100.0,
    )

    manager = CrawlerManager(primary=primary, fallback=fallback, settings=settings)
    result = await manager.fetch_page("https://example.com", CrawlSession())

    assert result.backend_used == BackendName.WEBCLAW
    assert primary.fetch.await_count == 1
    fallback.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_colly_dns_failure_is_retried_then_falls_back(settings: Settings) -> None:
    primary = AsyncMock()
    fallback = AsyncMock()
    primary.fetch.return_value = PageFetchResult(
        url="https://example.com",
        success=False,
        error="[Errno 11001] getaddrinfo failed",
        backend_used=BackendName.COLLY,
    )
    fallback.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><body>" + ("content " * 100) + "</body></html>",
        backend_used=BackendName.WEBCLAW,
        response_time_ms=100.0,
    )

    manager = CrawlerManager(primary=primary, fallback=fallback, settings=settings)
    result = await manager.fetch_page("https://example.com", CrawlSession())

    assert result.backend_used == BackendName.WEBCLAW
    # Initial attempt + crawler_max_retries
    assert primary.fetch.await_count == settings.crawler_max_retries + 1
    fallback.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_http_dns_failure_is_retried(settings: Settings) -> None:
    settings = settings.model_copy(update={"use_webclaw_fallback": False})
    primary = AsyncMock()
    fallback = AsyncMock()
    http_fallback = AsyncMock()
    primary.fetch.return_value = PageFetchResult(
        url="https://example.com",
        success=False,
        error="Connection refused",
        backend_used=BackendName.COLLY,
    )
    http_fallback.fetch.side_effect = [
        PageFetchResult(
            url="https://example.com",
            success=False,
            error="[Errno 11001] getaddrinfo failed",
            backend_used=BackendName.HTTP,
        ),
        PageFetchResult(
            url="https://example.com",
            status_code=200,
            success=True,
            html="<html><body>" + ("content " * 100) + "</body></html>",
            backend_used=BackendName.HTTP,
        ),
    ]

    manager = CrawlerManager(
        primary=primary,
        fallback=fallback,
        http_fallback=http_fallback,
        settings=settings,
    )
    result = await manager.fetch_page("https://example.com", CrawlSession())

    assert result.success is True
    assert result.backend_used == BackendName.HTTP
    assert http_fallback.fetch.await_count == 2


@pytest.mark.asyncio
async def test_both_backends_fail_falls_through_to_http(settings: Settings) -> None:
    primary = AsyncMock()
    fallback = AsyncMock()
    http_fallback = AsyncMock()
    primary.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=403,
        success=False,
        html="forbidden",
        backend_used=BackendName.COLLY,
        error="403",
    )
    fallback.fetch.return_value = PageFetchResult(
        url="https://example.com",
        success=False,
        backend_used=BackendName.WEBCLAW,
        error="API unavailable",
    )
    http_fallback.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><body>" + ("word " * 200) + "</body></html>",
        backend_used=BackendName.HTTP,
        response_time_ms=40.0,
    )

    manager = CrawlerManager(
        primary=primary,
        fallback=fallback,
        http_fallback=http_fallback,
        settings=settings,
    )
    result = await manager.fetch_page("https://example.com", CrawlSession())

    assert result.success is True
    assert result.backend_used == BackendName.HTTP
    http_fallback.fetch.assert_called_once()


@pytest.mark.asyncio
async def test_all_backends_fail_gracefully(settings: Settings) -> None:
    primary = AsyncMock()
    fallback = AsyncMock()
    http_fallback = AsyncMock()
    primary.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=403,
        success=False,
        html="forbidden",
        backend_used=BackendName.COLLY,
        error="403",
    )
    fallback.fetch.return_value = PageFetchResult(
        url="https://example.com",
        success=False,
        backend_used=BackendName.WEBCLAW,
        error="API unavailable",
    )
    http_fallback.fetch.return_value = PageFetchResult(
        url="https://example.com",
        success=False,
        backend_used=BackendName.HTTP,
        error="Connection reset",
    )

    manager = CrawlerManager(
        primary=primary,
        fallback=fallback,
        http_fallback=http_fallback,
        settings=settings,
    )
    result = await manager.fetch_page("https://example.com", CrawlSession())

    assert result.success is False
    assert result.error == "Connection reset"
    assert result.backend_used == BackendName.HTTP


@pytest.mark.asyncio
async def test_http_fallback_when_webclaw_disabled(settings: Settings) -> None:
    settings = settings.model_copy(update={"use_webclaw_fallback": False})
    primary = AsyncMock()
    fallback = AsyncMock()
    http_fallback = AsyncMock()
    primary.fetch.return_value = PageFetchResult(
        url="https://example.com",
        success=False,
        error="Connection refused",
        backend_used=BackendName.COLLY,
    )
    http_fallback.fetch.return_value = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><body>" + ("content " * 100) + "</body></html>",
        backend_used=BackendName.HTTP,
    )

    manager = CrawlerManager(
        primary=primary,
        fallback=fallback,
        http_fallback=http_fallback,
        settings=settings,
    )
    result = await manager.fetch_page("https://example.com", CrawlSession())

    assert result.backend_used == BackendName.HTTP
    fallback.fetch.assert_not_called()
    http_fallback.fetch.assert_called_once()
