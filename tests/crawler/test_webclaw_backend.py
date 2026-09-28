"""Webclaw backend unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import Settings
from app.crawler.backends.webclaw_backend import WebclawBackend
from app.crawler.models import BackendName, CrawlSession


@pytest.fixture
def settings() -> Settings:
    return Settings(webclaw_base_url="http://webclaw:3000")


@pytest.mark.asyncio
async def test_webclaw_fetch_success(settings: Settings) -> None:
    """Webclaw backend should map scrape JSON without auth."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "url": "https://example.com",
        "markdown": "# Hello",
        "text": "Hello",
        "metadata": {"title": "Example"},
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    backend = WebclawBackend(settings=settings, client=mock_client)
    result = await backend.fetch("https://example.com", session=CrawlSession())

    assert result.success is True
    assert result.backend_used == BackendName.WEBCLAW
    assert result.markdown == "# Hello"
    assert result.text == "Hello"

    call_kwargs = mock_client.post.call_args
    assert call_kwargs[0][0].endswith("/v1/scrape")
    assert "Authorization" not in (call_kwargs[1].get("headers") or {})


@pytest.mark.asyncio
async def test_webclaw_fetch_no_authorization_header(settings: Settings) -> None:
    """Local Webclaw requests must not send Authorization."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"url": "https://example.com", "text": "ok"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    backend = WebclawBackend(settings=settings, client=mock_client)
    await backend.fetch("https://example.com", session=CrawlSession())

    _, kwargs = mock_client.post.call_args
    headers = kwargs.get("headers") or {}
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_webclaw_fetch_http_error(settings: Settings) -> None:
    """HTTP errors should return failed PageFetchResult without raising."""
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_response.text = "Service unavailable"

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    backend = WebclawBackend(settings=settings, client=mock_client)
    result = await backend.fetch("https://example.com", session=CrawlSession())

    assert result.success is False
    assert result.status_code == 503
    assert "503" in (result.error or "")


@pytest.mark.asyncio
async def test_webclaw_fetch_transport_error(settings: Settings) -> None:
    """Transport failures should be handled gracefully."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

    backend = WebclawBackend(settings=settings, client=mock_client)
    result = await backend.fetch("https://example.com", session=CrawlSession())

    assert result.success is False
    assert result.backend_used == BackendName.WEBCLAW
    assert "Connection refused" in (result.error or "")


@pytest.mark.asyncio
async def test_webclaw_aclose_owned_client(settings: Settings) -> None:
    """Backend should close client it owns."""
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        backend = WebclawBackend(settings=settings)
        await backend._get_client()
        await backend.aclose()

        mock_client.aclose.assert_called_once()
