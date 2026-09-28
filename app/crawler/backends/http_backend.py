"""Direct HTTP fetch backend used when sidecars are unavailable."""

import time

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.crawler.models import BackendName, CrawlSession, PageFetchResult

logger = get_logger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

_SSL_CERT_ERROR_MARKERS = (
    "certificate verify failed",
    "certificate has expired",
    "sslcertverificationerror",
    "certificate_verify_failed",
)


def _is_ssl_cert_error(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _SSL_CERT_ERROR_MARKERS)


class HttpBackend:
    """Tertiary fetch backend via direct httpx GET."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def fetch(self, url: str, *, session: CrawlSession) -> PageFetchResult:
        """Fetch URL directly over HTTP."""
        start = time.perf_counter()
        cookies = {c["name"]: c["value"] for c in session.cookies if "name" in c and "value" in c}
        headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

        try:
            client = await self._get_client()
            response = await client.get(
                url,
                headers=headers,
                cookies=cookies or None,
                follow_redirects=True,
                timeout=self.settings.crawler_timeout_seconds,
            )
            return self._to_result(url, response, start, session)
        except Exception as exc:
            if _is_ssl_cert_error(exc):
                logger.warning(
                    "HTTP TLS verification failed; retrying without certificate verify",
                    extra={"url": url, "error": str(exc), "backend": BackendName.HTTP},
                )
                try:
                    return await self._fetch_insecure(url, headers, cookies, session, start)
                except Exception as insecure_exc:
                    return self._failure_result(url, start, insecure_exc)

            return self._failure_result(url, start, exc)

    async def _fetch_insecure(
        self,
        url: str,
        headers: dict[str, str],
        cookies: dict[str, str],
        session: CrawlSession,
        start: float,
    ) -> PageFetchResult:
        """One-shot fetch with TLS verification disabled (expired/misconfigured certs)."""
        async with httpx.AsyncClient(verify=False, proxy=self.settings.proxy_url) as client:
            response = await client.get(
                url,
                headers=headers,
                cookies=cookies or None,
                follow_redirects=True,
                timeout=self.settings.crawler_timeout_seconds,
            )
        return self._to_result(url, response, start, session)

    def _to_result(
        self,
        url: str,
        response: httpx.Response,
        start: float,
        session: CrawlSession,
    ) -> PageFetchResult:
        elapsed_ms = (time.perf_counter() - start) * 1000
        response_cookies = [
            {"name": name, "value": value} for name, value in response.cookies.items()
        ]
        if response_cookies:
            session.update_cookies(response_cookies)

        content_type = response.headers.get("content-type") or ""
        html = response.text if "html" in content_type.lower() or not content_type else ""
        if not html and response.status_code < 400:
            html = response.text

        success = bool(html) and response.status_code < 400
        return PageFetchResult(
            url=str(response.url),
            status_code=response.status_code,
            success=success,
            html=html or None,
            content_type=content_type or None,
            backend_used=BackendName.HTTP,
            response_time_ms=elapsed_ms,
            error=None if success else f"HTTP {response.status_code}",
            cookies=response_cookies,
        )

    def _failure_result(self, url: str, start: float, exc: BaseException) -> PageFetchResult:
        elapsed_ms = (time.perf_counter() - start) * 1000
        error_msg = str(exc)
        logger.warning(
            "HTTP backend fetch failed",
            extra={"url": url, "error": error_msg, "backend": BackendName.HTTP},
        )
        return PageFetchResult(
            url=url,
            status_code=None,
            success=False,
            backend_used=BackendName.HTTP,
            response_time_ms=elapsed_ms,
            error=error_msg,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(proxy=self.settings.proxy_url)
        self._owns_client = True
        if self.settings.proxy_url:
            logger.info(
                "HTTP backend using outbound proxy",
                extra={"proxy_host": self.settings.proxy_host, "backend": BackendName.HTTP},
            )
        return self._client

    async def aclose(self) -> None:
        """Close owned HTTP client."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
