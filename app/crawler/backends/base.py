"""Crawler backend protocol."""

from typing import Protocol

from app.crawler.models import CrawlSession, PageFetchResult


class CrawlerBackend(Protocol):
    """Interface for pluggable crawl fetch backends."""

    async def fetch(self, url: str, *, session: CrawlSession) -> PageFetchResult:
        """Fetch a single URL and return unified page result."""
        ...
