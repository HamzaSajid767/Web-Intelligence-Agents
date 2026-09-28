"""CollyBackend unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import Settings
from app.crawler.backends.colly_backend import CollyBackend
from app.crawler.models import BackendName, CrawlSession


@pytest.mark.asyncio
async def test_colly_backend_includes_proxy_when_enabled() -> None:
    settings = Settings(
        PROXY_ENABLED=True,
        PROXY_HOST="p.webshare.io",
        PROXY_PORT=80,
        PROXY_USERNAME="user",
        PROXY_PASSWORD="pass",
        COLLY_URL="http://colly:8081",
        COLLY_TIMEOUT_SECONDS=10,
        CRAWLER_RESPECT_ROBOTS_TXT=False,
    )
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "url": "https://example.com/",
        "status_code": 200,
        "html": "<html><body>ok</body></html>",
        "content_type": "text/html",
        "cookies": [],
        "error": None,
    }

    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_response)

    backend = CollyBackend(settings=settings, client=client)
    result = await backend.fetch("https://example.com/", session=CrawlSession())

    assert result.success is True
    assert result.backend_used == BackendName.COLLY
    payload = client.post.await_args.kwargs["json"]
    assert payload["proxy"] == "http://user:pass@p.webshare.io:80"


@pytest.mark.asyncio
async def test_colly_backend_omits_proxy_when_disabled() -> None:
    settings = Settings(
        PROXY_ENABLED=False,
        COLLY_URL="http://colly:8081",
        COLLY_TIMEOUT_SECONDS=10,
    )
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "url": "https://example.com/",
        "status_code": 200,
        "html": "<html><body>ok</body></html>",
        "content_type": "text/html",
        "cookies": [],
        "error": None,
    }

    client = AsyncMock()
    client.post = AsyncMock(return_value=mock_response)

    backend = CollyBackend(settings=settings, client=client)
    await backend.fetch("https://example.com/", session=CrawlSession())

    payload = client.post.await_args.kwargs["json"]
    assert "proxy" not in payload
