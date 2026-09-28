"""Website crawling service."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from urllib.parse import urlparse

from app.analysis.site_validity import is_soft_404_page
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.url_identity import (
    choose_canonical_url,
    normalize_identity_url,
    same_org_host,
)
from app.crawler.adapters import cap_page_data, fetch_result_to_page_data
from app.crawler.manager import CrawlerManager
from app.crawler.models import CrawlResult, CrawlSession, MAX_CLEAN_TEXT_LENGTH, PageData, PageFetchResult

__all__ = [
    "CrawlerService",
    "CrawlResult",
    "PageData",
    "MAX_CLEAN_TEXT_LENGTH",
]

logger = get_logger(__name__)

_PRIORITY_PATH_KEYWORDS = (
    "contact",
    "about",
    "about-us",
    "services",
    "service",
    "our-services",
    "team",
    "our-team",
    "staff",
    "people",
    "locations",
    "location",
    "offices",
    "get-in-touch",
    "support",
    "reach-us",
    "connect",
)

_DEPRIORITIZE_PATH_MARKERS = (
    "/login",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/register",
    "/cart",
    "/checkout",
    "/search",
    "/wp-admin",
    "/wp-login",
    "/feed",
    "/tag/",
    "/category/",
    "/author/",
)

_ASSET_EXTENSIONS = (
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".zip",
    ".mp4",
    ".mp3",
    ".ico",
)


def _priority_rank(url: str, link_text: str = "") -> int:
    """Lower rank is crawled sooner."""
    path = urlparse(url).path.lower()
    haystack = f"{path} {link_text.lower()}"
    if path in {"", "/"}:
        return 0
    if any(marker in path for marker in _DEPRIORITIZE_PATH_MARKERS):
        return 90
    if any(
        re.search(rf"(^|[/_\-\s]){re.escape(keyword)}([/_\-\s]|$)", haystack)
        for keyword in _PRIORITY_PATH_KEYWORDS
    ):
        return 10
    return 50


def _is_asset_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in _ASSET_EXTENSIONS)


class CrawlerService:
    """Async BFS crawler for website audits using hybrid backend manager."""

    def __init__(
        self,
        settings: Settings | None = None,
        manager: CrawlerManager | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.max_pages = self.settings.crawler_max_pages
        self.concurrency = max(1, self.settings.crawler_concurrency)
        self.manager = manager or CrawlerManager(settings=self.settings)

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for deduplication via shared identity rules."""
        return normalize_identity_url(url)

    def _is_same_org_domain(self, base_url: str, target_url: str) -> bool:
        """Allow same host or www/apex remap."""
        return same_org_host(base_url, target_url)

    def _is_same_domain(self, base_url: str, target_url: str) -> bool:
        """Check if target is on the same organization host (www-insensitive)."""
        return same_org_host(base_url, target_url)

    def _dequeue_batch(self, queue: list[str], visited: set[str], limit: int) -> list[str]:
        """Pop up to `limit` unvisited URLs from the frontier."""
        batch: list[str] = []
        while queue and len(batch) < limit:
            current_url = queue.pop(0)
            if current_url in visited:
                continue
            visited.add(current_url)
            batch.append(current_url)
        return batch

    def _enqueue_internal_links(
        self,
        website_url: str,
        page: PageData,
        *,
        visited: set[str],
        queue: list[str],
        queued: set[str],
    ) -> None:
        candidates: list[tuple[int, str]] = []
        for link in page.links:
            link_url = link.get("url", "")
            if not link_url or _is_asset_url(link_url):
                continue
            if link.get("type") != "internal" or not self._is_same_domain(website_url, link_url):
                continue
            normalized = self._normalize_url(link_url)
            if normalized in visited or normalized in queued:
                continue
            queued.add(normalized)
            link_text = link.get("text") or ""
            candidates.append((_priority_rank(normalized, link_text), normalized))

        candidates.sort(key=lambda item: item[0])
        priority = [url for rank, url in candidates if rank <= 10]
        normal = [url for rank, url in candidates if rank > 10]
        queue[:0] = priority
        queue.extend(normal)

    async def _fetch_one(
        self,
        url: str,
        session: CrawlSession,
        semaphore: asyncio.Semaphore,
    ) -> tuple[str, PageFetchResult | None, Exception | None]:
        async with semaphore:
            try:
                return url, await self.manager.fetch_page(url, session=session), None
            except Exception as exc:
                return url, None, exc

    def _apply_fetch_result(
        self,
        website_url: str,
        current_url: str,
        fetch_result: PageFetchResult | None,
        exc: Exception | None,
        result: CrawlResult,
        *,
        visited: set[str],
        queue: list[str],
        queued: set[str],
        is_seed: bool = False,
    ) -> str:
        """Apply fetch outcome; return updated crawl domain URL."""
        crawl_domain = website_url
        if exc is not None:
            error_msg = f"Failed to crawl {current_url}: {exc}"
            logger.warning(error_msg)
            result.errors.append(error_msg)
            return crawl_domain

        assert fetch_result is not None

        content_type = fetch_result.content_type or ""
        if content_type and "text/html" not in content_type.lower():
            if not fetch_result.html:
                return crawl_domain

        if not fetch_result.success and not fetch_result.html:
            error_msg = fetch_result.error or f"Failed to crawl {current_url}"
            result.errors.append(error_msg)
            return crawl_domain

        if not fetch_result.success:
            # Unsuccessful fetch with a non-empty body (e.g. a bot/CAPTCHA challenge
            # shell): still recorded as a failed page below, but the reason must
            # surface here too, otherwise crawl_result.errors stays empty and the
            # eventual "no usable pages" error loses its root cause.
            result.errors.append(fetch_result.error or f"Failed to crawl {current_url}")

        final_url = fetch_result.url or current_url
        meta = dict(fetch_result.metadata or {})
        meta.setdefault("requested_url", current_url)
        meta["final_url"] = final_url
        if final_url != current_url:
            meta["redirected"] = True
            hop = {
                "from": current_url,
                "to": final_url,
                "status_code": str(fetch_result.status_code or ""),
            }
            result.redirect_chain.append({"from": current_url, "to": final_url})
            result.redirect_history.append(hop)
        fetch_result.metadata = meta
        fetch_result.url = final_url

        if is_seed and final_url:
            result.final_url = final_url
            html_canonical = None
            page_meta = meta
            # page metadata may hold HTML canonical after conversion; check raw too
            if isinstance(page_meta.get("canonical"), str):
                html_canonical = page_meta["canonical"]

            # Prefer adopting final host when leaving the submitted org host.
            if not self._is_same_domain(website_url, final_url):
                crawl_domain = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
                logger.info(
                    "Seed URL redirected to new host; adopting canonical domain",
                    extra={
                        "requested_url": website_url,
                        "final_url": final_url,
                    },
                )

            # Convert first so HTML-extracted metadata (incl. canonical) is available.
            page_data = fetch_result_to_page_data(fetch_result)
            capped = PageData(**cap_page_data(page_data.model_dump()))
            page_dict = capped.model_dump()
            if is_soft_404_page(page_dict):
                capped.success = False
                soft_meta = dict(capped.metadata or {})
                soft_meta["soft_404"] = True
                capped.metadata = soft_meta

            html_canonical = (capped.metadata or {}).get("canonical") or html_canonical
            canonical = choose_canonical_url(
                result.submitted_url or website_url,
                final_url=final_url,
                html_canonical=html_canonical if isinstance(html_canonical, str) else None,
            )
            result.canonical_url = canonical
            result.canonical_website_url = canonical

            result.pages.append(capped)
            if capped.success:
                self._enqueue_internal_links(
                    crawl_domain if result.canonical_url else website_url,
                    capped,
                    visited=visited,
                    queue=queue,
                    queued=queued,
                )
            return crawl_domain if result.canonical_url else website_url

        page_data = fetch_result_to_page_data(fetch_result)
        capped = PageData(**cap_page_data(page_data.model_dump()))
        page_dict = capped.model_dump()
        if is_soft_404_page(page_dict):
            capped.success = False
            soft_meta = dict(capped.metadata or {})
            soft_meta["soft_404"] = True
            capped.metadata = soft_meta

        result.pages.append(capped)
        if capped.success:
            self._enqueue_internal_links(
                crawl_domain if result.canonical_url else website_url,
                capped,
                visited=visited,
                queue=queue,
                queued=queued,
            )
        return crawl_domain if result.canonical_url else website_url

    async def crawl(self, website_url: str) -> CrawlResult:
        """Crawl homepage and up to max_pages internal pages (parallel frontier)."""
        started = time.perf_counter()
        submitted = normalize_identity_url(website_url)
        result = CrawlResult(website_url=submitted, submitted_url=submitted)
        visited: set[str] = set()
        start_url = submitted
        queue: list[str] = [start_url]
        queued: set[str] = {start_url}
        session = CrawlSession()
        semaphore = asyncio.Semaphore(self.concurrency)
        crawl_domain = submitted
        seed_seen = False

        try:
            while queue and len(result.pages) < self.max_pages:
                remaining = self.max_pages - len(result.pages)
                batch = self._dequeue_batch(
                    queue,
                    visited,
                    min(self.concurrency, remaining),
                )
                if not batch:
                    break

                outcomes = await asyncio.gather(
                    *[self._fetch_one(url, session, semaphore) for url in batch]
                )

                for current_url, fetch_result, exc in outcomes:
                    if len(result.pages) >= self.max_pages:
                        break
                    is_seed = not seed_seen and current_url == start_url
                    if is_seed:
                        seed_seen = True
                    crawl_domain = self._apply_fetch_result(
                        crawl_domain,
                        current_url,
                        fetch_result,
                        exc,
                        result,
                        visited=visited,
                        queue=queue,
                        queued=queued,
                        is_seed=is_seed,
                    )
        finally:
            await self.manager.aclose()

        result.total_pages = len(result.pages)
        if result.canonical_url:
            result.website_url = result.canonical_url
            result.canonical_website_url = result.canonical_url
        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "Crawl completed",
            extra={
                "website_url": result.website_url,
                "pages": result.total_pages,
                "duration_ms": duration_ms,
                "concurrency": self.concurrency,
                "canonical_url": result.canonical_url,
                "submitted_url": result.submitted_url,
                "final_url": result.final_url,
            },
        )
        return result

    def to_state_dict(self, crawl_result: CrawlResult) -> dict[str, Any]:
        """Convert crawl result to audit state dict."""
        data: dict[str, Any] = {
            "website_url": crawl_result.website_url,
            "submitted_url": crawl_result.submitted_url or crawl_result.website_url,
            "pages": [page.model_dump() for page in crawl_result.pages],
            "total_pages": crawl_result.total_pages,
            "errors": crawl_result.errors,
            "summary": "",
            "redirect_chain": list(crawl_result.redirect_chain),
            "redirect_history": list(crawl_result.redirect_history or crawl_result.redirect_chain),
        }
        if crawl_result.final_url:
            data["final_url"] = crawl_result.final_url
        if crawl_result.canonical_url:
            data["canonical_url"] = crawl_result.canonical_url
            data["canonical_website_url"] = crawl_result.canonical_url
        return data
