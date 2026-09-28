"""Colly sidecar HTTP backend."""

import time
from typing import Any

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


class CollyBackend:
    """Primary fetch backend via Colly Go sidecar."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def fetch(self, url: str, *, session: CrawlSession) -> PageFetchResult:
        """Fetch URL through the Colly sidecar service."""
        start = time.perf_counter()
        payload: dict[str, Any] = {
            "url": url,
            "timeout_seconds": self.settings.colly_timeout_seconds,
            "follow_redirects": True,
            "respect_robots_txt": self.settings.crawler_respect_robots_txt,
            "cookies": session.cookies,
            "user_agent": DEFAULT_USER_AGENT,
        }
        if self.settings.proxy_url:
            payload["proxy"] = self.settings.proxy_url

        try:
            client = await self._get_client()
            response = await client.post(
                f"{self.settings.colly_url.rstrip('/')}/v1/fetch",
                json=payload,
                timeout=self.settings.colly_timeout_seconds + 5,
            )
            data = response.json()
            elapsed_ms = (time.perf_counter() - start) * 1000

            cookies = data.get("cookies") or []
            session.update_cookies(cookies)

            html = data.get("html") or ""
            status_code = data.get("status_code")
            content_type = data.get("content_type") or ""
            error = data.get("error")

            success = bool(html) and (error is None) and (status_code is None or status_code < 400)

            return PageFetchResult(
                url=data.get("url") or url,
                status_code=status_code,
                success=success,
                html=html or None,
                content_type=content_type or None,
                backend_used=BackendName.COLLY,
                response_time_ms=data.get("response_time_ms") or elapsed_ms,
                error=error,
                cookies=cookies,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            error_msg = str(exc)
            hint = ""
            if "connection" in error_msg.lower():
                hint = f" (is colly-sidecar running at {self.settings.colly_url}?)"
            logger.warning(
                "Colly backend fetch failed",
                extra={"url": url, "error": error_msg, "backend": BackendName.COLLY},
            )
            return PageFetchResult(
                url=url,
                status_code=None,
                success=False,
                backend_used=BackendName.COLLY,
                response_time_ms=elapsed_ms,
                error=f"{error_msg}{hint}",
            )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient()
        self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Close owned HTTP client."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
