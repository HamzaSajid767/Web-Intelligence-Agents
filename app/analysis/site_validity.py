"""Detect parked, placeholder, and otherwise unusable websites."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# Minimum aggregate clean text length to consider a site usable.
_MIN_TOTAL_TEXT_CHARS = 120
_MIN_PAGE_TEXT_CHARS = 40

_INVALID_TITLE_PATTERNS = (
    r"connectyourdomain",
    r"domain\s+not\s+connected",
    r"website\s+coming\s+soon",
    r"coming\s+soon",
    r"under\s+construction",
    r"parked\s+domain",
    r"domain\s+for\s+sale",
    r"this\s+domain\s+is\s+for\s+sale",
    r"buy\s+this\s+domain",
    r"domain\s+has\s+expired",
    r"expired\s+domain",
    r"website\s+expired",
    r"account\s+suspended",
    r"suspended\s+domain",
    r"default\s+web\s+site\s+page",
    r"apache2?\s+ubuntu\s+default",
    r"iis\s+windows\s+server",
    r"welcome\s+to\s+nginx",
    r"404\s+page",
    r"page\s+not\s+found",
    r"not\s+found",
    r"error\s+404",
    r"cloudflare",
    r"attention\s+required",
    r"just\s+a\s+moment",
    r"wix\.com",
)

_INVALID_BODY_PATTERNS = (
    r"connectyourdomain\s+error",
    r"this\s+domain\s+isn'?t\s+connected",
    r"domain\s+is\s+parked",
    r"this\s+web\s+page\s+is\s+parked",
    r"domain\s+for\s+sale",
    r"buy\s+this\s+domain",
    r"godaddy\s+parked",
    r"sedo\s+parking",
    r"hugedomains",
    r"namecheap\s+parking",
    r"no\s+website\s+configured",
    r"website\s+has\s+not\s+been\s+published",
    r"this\s+site\s+can'?t\s+be\s+reached",
    r"there\s+is\s+nothing\s+here",
    r"future\s+home\s+of",
    r"under\s+maintenance",
    r"be\s+right\s+back",
    r"sorry\.\.\.\s+something\s+didn'?t\s+add\s+up",
)

_SOFT_404_PATTERNS = (
    r"page\s+not\s+found",
    r"404\s+not\s+found",
    r"404\s+error",
    r"cannot\s+be\s+found",
    r"does\s+not\s+exist",
    r"no\s+longer\s+available",
)


@dataclass
class SiteValidity:
    """Outcome of website usability assessment."""

    is_valid: bool
    reason: str | None = None
    signals: list[str] = field(default_factory=list)
    usable_page_count: int = 0
    total_text_chars: int = 0
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _matches_any(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return pattern
    return None


def _page_text(page: dict[str, Any]) -> str:
    parts = [
        page.get("clean_text") or "",
        page.get("markdown") or "",
        page.get("title") or "",
    ]
    meta = page.get("metadata") or {}
    if isinstance(meta, dict):
        parts.append(meta.get("title") or "")
        parts.append(meta.get("description") or "")
    return " ".join(p for p in parts if p)


def is_soft_404_page(page: dict[str, Any]) -> bool:
    """Return True if a page looks like a soft-404 / error page."""
    text = _norm(_page_text(page))
    title = _norm(page.get("title") or (page.get("metadata") or {}).get("title"))
    if _matches_any(title, _SOFT_404_PATTERNS):
        return True
    if len(text) < 400 and _matches_any(text, _SOFT_404_PATTERNS):
        return True
    status = page.get("status_code")
    if isinstance(status, int) and status >= 400:
        return True
    return False


def assess_site_validity(
    pages: list[dict[str, Any]] | None,
    *,
    crawl_errors: list[str] | None = None,
) -> SiteValidity:
    """Assess whether crawled pages represent a real usable business website."""
    pages = list(pages or [])
    signals: list[str] = []
    if not pages:
        return SiteValidity(
            is_valid=False,
            reason="No pages crawled",
            signals=["no_pages"],
            usable_page_count=0,
            total_text_chars=0,
        )

    usable: list[dict[str, Any]] = []
    total_text = 0
    for page in pages:
        if page.get("success") is False:
            signals.append(f"failed_page:{page.get('url')}")
            continue
        if is_soft_404_page(page):
            signals.append(f"soft_404:{page.get('url')}")
            continue
        text = _page_text(page)
        text_len = len(text.strip())
        total_text += text_len
        title = _norm(page.get("title") or (page.get("metadata") or {}).get("title"))
        body = _norm(text)

        invalid_title = _matches_any(title, _INVALID_TITLE_PATTERNS)
        if invalid_title:
            signals.append(f"invalid_title:{invalid_title}")
            continue
        invalid_body = _matches_any(body, _INVALID_BODY_PATTERNS)
        if invalid_body and text_len < 1500:
            signals.append(f"invalid_body:{invalid_body}")
            continue
        if text_len < _MIN_PAGE_TEXT_CHARS and not (page.get("headings") or []):
            signals.append(f"thin_page:{page.get('url')}")
            continue
        usable.append(page)

    if not usable:
        reason = "Only error, parked, or empty placeholder pages were crawled"
        if crawl_errors:
            reason = f"{reason}; crawl_errors={'; '.join(crawl_errors[:3])}"
        return SiteValidity(
            is_valid=False,
            reason=reason,
            signals=signals or ["no_usable_pages"],
            usable_page_count=0,
            total_text_chars=total_text,
        )

    usable_text = sum(len(_page_text(p).strip()) for p in usable)
    if usable_text < _MIN_TOTAL_TEXT_CHARS:
        return SiteValidity(
            is_valid=False,
            reason=f"Insufficient page content ({usable_text} chars across usable pages)",
            signals=signals + ["insufficient_text"],
            usable_page_count=len(usable),
            total_text_chars=usable_text,
            confidence=0.9,
        )

    # Homepage-level parking still invalidates even if one thin asset slipped through.
    homepage = usable[0]
    home_body = _norm(_page_text(homepage))
    home_title = _norm(homepage.get("title") or (homepage.get("metadata") or {}).get("title"))
    for pattern_hit in (
        _matches_any(home_title, _INVALID_TITLE_PATTERNS),
        _matches_any(home_body, _INVALID_BODY_PATTERNS),
    ):
        if pattern_hit:
            return SiteValidity(
                is_valid=False,
                reason=f"Homepage matches unusable site pattern: {pattern_hit}",
                signals=signals + [f"homepage_invalid:{pattern_hit}"],
                usable_page_count=0,
                total_text_chars=usable_text,
            )

    return SiteValidity(
        is_valid=True,
        reason=None,
        signals=signals,
        usable_page_count=len(usable),
        total_text_chars=usable_text,
        confidence=0.95 if len(usable) > 1 else 0.8,
    )
