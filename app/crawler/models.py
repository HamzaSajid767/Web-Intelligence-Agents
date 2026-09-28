"""Crawler domain models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class BackendName(StrEnum):
    """Crawler backend identifiers."""

    COLLY = "colly"
    WEBCLAW = "webclaw"
    HTTP = "http"


class PageFetchResult(BaseModel):
    """Unified per-page fetch result from any backend."""

    url: str
    status_code: int | None = None
    success: bool = False
    title: str | None = None
    html: str | None = None
    markdown: str | None = None
    text: str | None = None
    links: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    backend_used: Literal["colly", "webclaw", "http"]
    response_time_ms: float = 0.0
    error: str | None = None
    cookies: list[dict[str, str]] = Field(default_factory=list)
    content_type: str | None = None


class PageData(BaseModel):
    """Single crawled page for audit pipeline consumption."""

    url: str
    title: str | None = None
    raw_html: str | None = None
    clean_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    headings: list[dict[str, Any]] = Field(default_factory=list)
    links: list[dict[str, Any]] = Field(default_factory=list)
    image_stats: dict[str, int] = Field(default_factory=dict)
    chatbot_signals: dict[str, Any] = Field(default_factory=dict)
    status_code: int | None = None
    success: bool = True
    markdown: str | None = None
    backend_used: Literal["colly", "webclaw", "http"] | None = None
    response_time_ms: float | None = None


class CrawlResult(BaseModel):
    """Result of a website crawl."""

    website_url: str
    pages: list[PageData] = Field(default_factory=list)
    total_pages: int = 0
    errors: list[str] = Field(default_factory=list)
    submitted_url: str | None = None
    final_url: str | None = None
    canonical_url: str | None = None
    # Compatibility alias kept in sync with canonical_url.
    canonical_website_url: str | None = None
    redirect_chain: list[dict[str, str]] = Field(default_factory=list)
    redirect_history: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_identity_fields(self) -> CrawlResult:
        if self.canonical_url and not self.canonical_website_url:
            self.canonical_website_url = self.canonical_url
        elif self.canonical_website_url and not self.canonical_url:
            self.canonical_url = self.canonical_website_url
        if self.redirect_history and not self.redirect_chain:
            self.redirect_chain = [
                {"from": str(h.get("from", "")), "to": str(h.get("to", ""))}
                for h in self.redirect_history
                if h.get("from") and h.get("to")
            ]
        elif self.redirect_chain and not self.redirect_history:
            self.redirect_history = list(self.redirect_chain)
        return self


class CrawlSession(BaseModel):
    """Per-crawl session state for cookie and redirect preservation."""

    cookies: list[dict[str, str]] = Field(default_factory=list)

    def update_cookies(self, new_cookies: list[dict[str, str]]) -> None:
        """Merge cookies by name, preserving latest values."""
        cookie_map = {c["name"]: c["value"] for c in self.cookies if "name" in c and "value" in c}
        for cookie in new_cookies:
            if "name" in cookie and "value" in cookie:
                cookie_map[cookie["name"]] = cookie["value"]
        self.cookies = [{"name": k, "value": v} for k, v in cookie_map.items()]


MAX_CLEAN_TEXT_LENGTH = 8000
MAX_RAW_HTML_LENGTH = 200_000
