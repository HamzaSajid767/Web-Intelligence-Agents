"""Hybrid crawler manager orchestrating backends with fallback."""

import asyncio

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.crawler.backends.base import CrawlerBackend
from app.crawler.backends.colly_backend import CollyBackend
from app.crawler.backends.http_backend import HttpBackend
from app.crawler.backends.webclaw_backend import WebclawBackend
from app.crawler.bot_detection import (
    BotDetectionResult,
    BotProtectionDetector,
    is_dns_failure,
    is_infrastructure_failure,
)
from app.crawler.models import BackendName, CrawlSession, PageFetchResult
from app.crawler.retry_policy import (
    compute_backoff_seconds,
    is_transient_error,
    should_retry_colly,
)

logger = get_logger(__name__)


class CrawlerManager:
    """Orchestrates Colly → Webclaw → direct HTTP fallback."""

    def __init__(
        self,
        primary: CrawlerBackend | None = None,
        fallback: CrawlerBackend | None = None,
        http_fallback: CrawlerBackend | None = None,
        settings: Settings | None = None,
        detector: BotProtectionDetector | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.primary = primary or CollyBackend(self.settings)
        self.fallback = fallback or WebclawBackend(self.settings)
        self.http_fallback = http_fallback or HttpBackend(self.settings)
        self.detector = detector or BotProtectionDetector(
            min_html_length=self.settings.crawler_min_html_length,
        )

    async def fetch_page(self, url: str, session: CrawlSession | None = None) -> PageFetchResult:
        """Fetch a page using Colly, then Webclaw, then direct HTTP."""
        started = asyncio.get_running_loop().time()
        crawl_session = session or CrawlSession()
        colly_result = await self._fetch_with_colly_retries(url, crawl_session)

        if is_infrastructure_failure(colly_result):
            logger.warning(
                "Colly fetch failed before receiving page content",
                extra={
                    "url": url,
                    "error": colly_result.error,
                    "backend": BackendName.COLLY,
                    "colly_url": self.settings.colly_url,
                },
            )
        else:
            bot = self.detector.analyze(colly_result)
            if colly_result.success and not bot.detected:
                self._log_success(colly_result)
                self._log_fetch_duration(url, colly_result.backend_used, started)
                return colly_result
            if bot.detected:
                self._log_bot_detection(url, bot)

        prior_result = colly_result

        if self.settings.use_webclaw_fallback:
            logger.info(
                "Switching to Webclaw",
                extra={"url": url, "backend": BackendName.WEBCLAW},
            )
            webclaw_result = await self.fallback.fetch(url, session=crawl_session)

            if webclaw_result.success:
                self._log_fallback_success(webclaw_result)
                self._log_fetch_duration(url, webclaw_result.backend_used, started)
                return webclaw_result

            logger.warning(
                "Webclaw extraction failed",
                extra={
                    "url": url,
                    "backend": BackendName.WEBCLAW,
                    "error": webclaw_result.error,
                },
            )
            prior_result = webclaw_result if webclaw_result.error else colly_result

        return await self._fetch_with_http(url, crawl_session, prior_result, started)

    async def _fetch_with_http(
        self,
        url: str,
        session: CrawlSession,
        prior_result: PageFetchResult,
        started: float,
    ) -> PageFetchResult:
        """Final direct-HTTP fallback when sidecars fail or are disabled."""
        logger.info(
            "Switching to HTTP fallback",
            extra={"url": url, "backend": BackendName.HTTP},
        )
        http_result = await self.http_fallback.fetch(url, session=session)
        max_retries = self.settings.crawler_max_retries
        for attempt in range(1, max_retries + 1):
            if http_result.success or not (
                is_dns_failure(http_result) or is_transient_error(http_result)
            ):
                break
            delay = compute_backoff_seconds(self.settings.crawler_retry_backoff_seconds, attempt)
            logger.info(
                "Retrying HTTP fallback fetch",
                extra={
                    "url": url,
                    "attempt": attempt,
                    "max_retries": max_retries,
                    "delay_seconds": delay,
                    "backend": BackendName.HTTP,
                    "error": http_result.error,
                },
            )
            await asyncio.sleep(delay)
            http_result = await self.http_fallback.fetch(url, session=session)

        if http_result.success:
            bot = self.detector.analyze(http_result)
            if not bot.detected:
                self._log_success(http_result)
                self._log_fetch_duration(url, http_result.backend_used, started)
                return http_result
            # Last fallback also hit a bot/security wall: relabel so callers and
            # site-validity checks see a clear reason instead of a false success.
            self._log_bot_detection(url, bot)
            http_result = http_result.model_copy(
                update={
                    "success": False,
                    "error": f"Bot protection detected ({bot.reason.value}): {bot.details}",
                }
            )

        logger.warning(
            "HTTP fallback failed",
            extra={
                "url": url,
                "backend": BackendName.HTTP,
                "error": http_result.error,
            },
        )
        final = http_result if http_result.error else prior_result
        self._log_fetch_duration(url, final.backend_used, started)
        return final

    def _log_fetch_duration(self, url: str, backend: str, started: float) -> None:
        duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
        logger.info(
            "Page fetch completed",
            extra={"url": url, "backend": backend, "duration_ms": duration_ms},
        )

    async def _fetch_with_colly_retries(
        self,
        url: str,
        session: CrawlSession,
    ) -> PageFetchResult:
        """Attempt Colly fetch with exponential backoff on transient HTTP failures."""
        max_retries = self.settings.crawler_max_retries
        result = await self.primary.fetch(url, session=session)

        if is_infrastructure_failure(result):
            return result

        for attempt in range(1, max_retries + 1):
            if not should_retry_colly(result, self.detector):
                break
            delay = compute_backoff_seconds(self.settings.crawler_retry_backoff_seconds, attempt)
            logger.info(
                "Retrying Colly fetch",
                extra={
                    "url": url,
                    "attempt": attempt,
                    "max_retries": max_retries,
                    "delay_seconds": delay,
                    "backend": BackendName.COLLY,
                },
            )
            await asyncio.sleep(delay)
            result = await self.primary.fetch(url, session=session)
            if is_infrastructure_failure(result):
                break

        return result

    def _log_success(self, result: PageFetchResult) -> None:
        logger.info(
            "Crawler fetch successful",
            extra={
                "backend": result.backend_used,
                "status_code": result.status_code,
                "response_time_ms": result.response_time_ms,
                "url": result.url,
            },
        )

    def _log_bot_detection(self, url: str, bot: BotDetectionResult) -> None:
        logger.warning(
            "Bot detection triggered",
            extra={
                "url": url,
                "reason": bot.reason.value if bot.reason else None,
                "details": bot.details,
                "backend": BackendName.COLLY,
            },
        )

    def _log_fallback_success(self, result: PageFetchResult) -> None:
        logger.info(
            "Webclaw extraction successful",
            extra={
                "backend": result.backend_used,
                "status_code": result.status_code,
                "response_time_ms": result.response_time_ms,
                "url": result.url,
            },
        )

    async def aclose(self) -> None:
        """Close backend clients."""
        for backend in (self.primary, self.fallback, self.http_fallback):
            aclose = getattr(backend, "aclose", None)
            if callable(aclose):
                await aclose()
