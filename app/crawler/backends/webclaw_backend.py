"""Local Webclaw server fallback backend."""

import re
import time
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.crawler.models import BackendName, CrawlSession, PageFetchResult

logger = get_logger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def _has_real_content(html: str | None, markdown: str | None, text: str | None) -> bool:
    """Return True only when some visible text was actually extracted.

    Webclaw can return HTTP 200 with a rendered-but-empty shell (e.g. a bot
    challenge page that never resolved), such as ``html="<body></body>"``.
    That string is truthy, so a plain `bool(html or markdown or text)` check
    misclassifies it as a successful extraction.
    """
    if (markdown or "").strip():
        return True
    if (text or "").strip():
        return True
    if html:
        visible = _TAG_RE.sub(" ", html)
        if re.sub(r"\s+", "", visible).strip():
            return True
    return False


class WebclawBackend:
    """Fallback fetch backend using self-hosted Webclaw REST API."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._owns_client = client is None

    async def fetch(self, url: str, *, session: CrawlSession) -> PageFetchResult:
        """Scrape URL via local Webclaw /v1/scrape endpoint."""
        start = time.perf_counter()
        payload: dict[str, Any] = {
            "url": url,
            "formats": ["markdown", "text", "html"],
            "only_main_content": False,
        }
        # Prefer env WEBCLAW_PROXY on the sidecar; also pass per-request when supported.
        if self.settings.proxy_url:
            payload["proxy"] = self.settings.proxy_url

        try:
            client = await self._get_client()
            response = await client.post(
                f"{self.settings.webclaw_base_url.rstrip('/')}/v1/scrape",
                json=payload,
                timeout=self.settings.crawler_timeout_seconds + 5,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            if response.status_code >= 400:
                error_body = response.text[:500]
                return PageFetchResult(
                    url=url,
                    status_code=response.status_code,
                    success=False,
                    backend_used=BackendName.WEBCLAW,
                    response_time_ms=elapsed_ms,
                    error=f"HTTP {response.status_code}: {error_body}",
                    cookies=session.cookies,
                )

            data = response.json()
            markdown = data.get("markdown")
            text = data.get("text") or data.get("llm")
            html = data.get("html") or data.get("raw_html")
            metadata = data.get("metadata") or {}
            warning = data.get("warning")

            success = _has_real_content(html, markdown, text)
            error_message = None
            if not success:
                error_message = warning or "Webclaw returned no extractable content (empty render)"

            return PageFetchResult(
                url=data.get("url") or url,
                status_code=response.status_code,
                success=success,
                html=html,
                markdown=markdown,
                text=text,
                metadata=metadata if isinstance(metadata, dict) else {},
                backend_used=BackendName.WEBCLAW,
                response_time_ms=elapsed_ms,
                error=error_message,
                cookies=session.cookies,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            error_msg = str(exc)
            hint = ""
            if "connection" in error_msg.lower():
                hint = f" (is webclaw running at {self.settings.webclaw_base_url}?)"
            logger.warning(
                "Webclaw backend fetch failed",
                extra={"url": url, "error": error_msg, "backend": BackendName.WEBCLAW},
            )
            return PageFetchResult(
                url=url,
                success=False,
                backend_used=BackendName.WEBCLAW,
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
