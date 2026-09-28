"""HttpBackend unit tests."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.core.config import Settings
from app.crawler.backends.http_backend import HttpBackend
from app.crawler.models import BackendName, CrawlSession


@pytest.mark.asyncio
async def test_http_backend_fetches_html() -> None:
    settings = Settings.model_construct(crawler_timeout_seconds=10)
    response = MagicMock()
    response.status_code = 200
    response.text = "<html><body>Hello</body></html>"
    response.url = "https://example.com/"
    response.headers = {"content-type": "text/html; charset=utf-8"}
    response.cookies = httpx.Cookies()

    client = AsyncMock()
    client.get = AsyncMock(return_value=response)

    backend = HttpBackend(settings=settings, client=client)
    result = await backend.fetch("https://example.com/", session=CrawlSession())

    assert result.success is True
    assert result.backend_used == BackendName.HTTP
    assert result.html and "Hello" in result.html
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_http_backend_connection_error() -> None:
    settings = Settings.model_construct(crawler_timeout_seconds=10)
    client = AsyncMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

    backend = HttpBackend(settings=settings, client=client)
    result = await backend.fetch("https://example.com/", session=CrawlSession())

    assert result.success is False
    assert result.backend_used == BackendName.HTTP
    assert result.error


@pytest.mark.asyncio
async def test_http_backend_retries_insecure_on_expired_cert(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings.model_construct(crawler_timeout_seconds=10)
    verify_client = AsyncMock()
    verify_client.get = AsyncMock(
        side_effect=httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired"
        )
    )

    insecure_response = MagicMock()
    insecure_response.status_code = 200
    insecure_response.text = "<html><body>Recovered</body></html>"
    insecure_response.url = "https://expired.example/"
    insecure_response.headers = {"content-type": "text/html"}
    insecure_response.cookies = httpx.Cookies()

    insecure_client = AsyncMock()
    insecure_client.get = AsyncMock(return_value=insecure_response)
    insecure_client.__aenter__ = AsyncMock(return_value=insecure_client)
    insecure_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "app.crawler.backends.http_backend.httpx.AsyncClient",
        MagicMock(return_value=insecure_client),
    )

    backend = HttpBackend(settings=settings, client=verify_client)
    result = await backend.fetch("https://expired.example/", session=CrawlSession())

    assert result.success is True
    assert result.html and "Recovered" in result.html
    verify_client.get.assert_awaited_once()
    insecure_client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_http_backend_creates_client_with_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        PROXY_ENABLED=True,
        PROXY_HOST="p.webshare.io",
        PROXY_PORT=80,
        PROXY_USERNAME="user",
        PROXY_PASSWORD="pass",
        CRAWLER_TIMEOUT_SECONDS=10,
    )
    response = MagicMock()
    response.status_code = 200
    response.text = "<html><body>Proxied</body></html>"
    response.url = "https://example.com/"
    response.headers = {"content-type": "text/html"}
    response.cookies = httpx.Cookies()

    created: dict[str, object] = {}
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)

    def _factory(*_args: object, **kwargs: object) -> AsyncMock:
        created.update(kwargs)
        return mock_client

    monkeypatch.setattr("app.crawler.backends.http_backend.httpx.AsyncClient", _factory)

    backend = HttpBackend(settings=settings)
    result = await backend.fetch("https://example.com/", session=CrawlSession())

    assert result.success is True
    assert created.get("proxy") == "http://user:pass@p.webshare.io:80"
