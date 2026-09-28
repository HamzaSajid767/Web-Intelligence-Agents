"""Extract emails, phone numbers, and social links from page content."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

PHONE_PATTERN = re.compile(
    r"(?:\+1[-.\s\u2013\u2014]?)?"
    r"\(?\d{3}\)?"
    r"[-.\s\u2013\u2014]?"
    r"\d{3}"
    r"[-.\s\u2013\u2014]?"
    r"\d{4}"
)

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

_NOISE_EMAIL_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
    ".ico",
)

SOCIAL_HOST_SUFFIXES = (
    "facebook.com",
    "fb.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "pinterest.com",
    "threads.net",
    "yelp.com",
)

# YouTube watch links are usually embeds/media, not firm social profiles.
_SOCIAL_REQUIRE_PATH_PREFIX = {
    "linkedin.com": ("/company/", "/in/", "/school/"),
    "facebook.com": ("/",),
    "instagram.com": ("/",),
}

_SHARE_INTENT_MARKERS = (
    "sharer.php",
    "sharearticle",
    "/intent/",
    "share?url=",
    "share.php",
)

# Non-profile paths that should not count as social profiles.
_NON_PROFILE_SOCIAL_PATH_MARKERS = (
    "/search/",
    "/search?",
    "/sharer/",
    "/share/",
)


def extract_contacts(
    html: str | None,
    text: str | None,
    markdown: str | None = None,
    *,
    base_url: str | None = None,
) -> dict[str, list[str]]:
    """Extract emails, phones, and social links from page content."""
    combined = "\n".join(part for part in (html, text, markdown) if part)
    html_for_scan = _strip_svg(html or "")
    phone_scan = "\n".join(part for part in (html_for_scan, text, markdown) if part)

    emails: set[str] = set()
    for match in EMAIL_PATTERN.findall(combined):
        if _is_valid_email(match):
            emails.add(match.lower())
    for match in re.findall(r'mailto:([^"\'>\s?]+)', combined, re.I):
        decoded = match.replace("%40", "@")
        if _is_valid_email(decoded):
            emails.add(decoded.lower())

    phones: set[str] = set()
    for match in re.findall(r"tel:([+\d\s().\u2013\u2014-]+)", combined, re.I):
        normalized = _normalize_phone(match)
        if normalized:
            phones.add(normalized)
    for match in PHONE_PATTERN.findall(phone_scan):
        normalized = _normalize_phone(match)
        if normalized:
            phones.add(normalized)

    social_links = _extract_social_links(html or "", base_url=base_url)

    if html:
        ld_emails, ld_phones, ld_social = _extract_json_ld_contacts(html, base_url=base_url)
        emails.update(ld_emails)
        phones.update(ld_phones)
        social_links.update(ld_social)

    return {
        "emails": sorted(emails),
        "phone_numbers": sorted(phones),
        "social_links": sorted(social_links),
    }


def aggregate_contacts(pages: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Merge contact fields across crawled page dicts."""
    emails: set[str] = set()
    phones: set[str] = set()
    social: set[str] = set()

    for page in pages:
        found = extract_contacts(
            page.get("raw_html"),
            page.get("clean_text"),
            page.get("markdown"),
            base_url=page.get("url"),
        )
        emails.update(found["emails"])
        phones.update(found["phone_numbers"])
        social.update(found["social_links"])

    return {
        "emails": sorted(emails),
        "phone_numbers": sorted(phones),
        "social_links": sorted(social),
    }


def _is_valid_email(email: str) -> bool:
    """Reject image/asset false positives and obviously invalid hosts."""
    candidate = email.strip().lower()
    if not candidate or "@" not in candidate:
        return False
    local, _, domain = candidate.partition("@")
    if not local or not domain or "." not in domain:
        return False
    if any(local.endswith(ext) for ext in _NOISE_EMAIL_EXTENSIONS):
        return False
    if any(domain.endswith(ext) for ext in _NOISE_EMAIL_EXTENSIONS):
        return False
    if domain.startswith(".") or ".." in domain:
        return False
    tld = domain.rsplit(".", 1)[-1]
    if len(tld) < 2 or not tld.isalpha():
        return False
    if domain in {"email.com", "domain.com", "sentry.io", "example.org"}:
        return False
    if "wixpress.com" in domain or "amazonaws.com" in domain:
        return False
    return bool(EMAIL_PATTERN.fullmatch(candidate))


def _extract_social_links(html: str, *, base_url: str | None = None) -> set[str]:
    """Collect absolute social profile URLs from anchor tags."""
    if not html.strip():
        return set()

    soup = BeautifulSoup(html, "lxml")
    found: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(base_url or "", href) if base_url else href
        normalized = _normalize_social_url(absolute)
        if normalized:
            found.add(normalized)
    return found


def _normalize_social_url(url: str) -> str | None:
    """Return a cleaned social URL or None if not a known social host."""
    if not url.startswith(("http://", "https://")):
        return None
    lowered = url.lower()
    if any(marker in lowered for marker in _SHARE_INTENT_MARKERS):
        return None
    # Skip naked video/watch embeds mistaken for profiles.
    if "youtube.com/watch" in lowered or "youtu.be/" in lowered:
        return None
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.lower()
    path_and_query = f"{path}?{parsed.query.lower()}" if parsed.query else path
    if any(marker in path_and_query for marker in _NON_PROFILE_SOCIAL_PATH_MARKERS):
        return None
    matched = next(
        (suffix for suffix in SOCIAL_HOST_SUFFIXES if host == suffix or host.endswith("." + suffix)),
        None,
    )
    if not matched:
        return None
    required = _SOCIAL_REQUIRE_PATH_PREFIX.get(matched)
    if required and not any(path.startswith(prefix) or path == prefix.rstrip("/") for prefix in required):
        # Allow facebook/instagram root profile paths with at least one segment.
        if matched in {"facebook.com", "instagram.com"} and path.count("/") >= 1 and len(path) > 1:
            pass
        elif matched == "linkedin.com":
            return None
    cleaned = url.split("#", 1)[0].split("?", 1)[0].rstrip("/")
    return cleaned


def _extract_json_ld_contacts(
    html: str,
    *,
    base_url: str | None = None,
) -> tuple[set[str], set[str], set[str]]:
    """Pull email, telephone, and sameAs social URLs from JSON-LD blocks."""
    emails: set[str] = set()
    phones: set[str] = set()
    social: set[str] = set()
    soup = BeautifulSoup(html, "lxml")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        _collect_json_ld_contacts(data, emails, phones, social, base_url=base_url)
    return emails, phones, social


def _collect_json_ld_contacts(
    data: Any,
    emails: set[str],
    phones: set[str],
    social: set[str],
    *,
    base_url: str | None = None,
) -> None:
    """Recursively collect contact fields from JSON-LD objects."""
    if isinstance(data, list):
        for item in data:
            _collect_json_ld_contacts(item, emails, phones, social, base_url=base_url)
        return
    if not isinstance(data, dict):
        return

    email_val = data.get("email")
    if isinstance(email_val, str):
        cleaned = email_val.lower().removeprefix("mailto:").strip()
        if _is_valid_email(cleaned):
            emails.add(cleaned)
    elif isinstance(email_val, list):
        for item in email_val:
            if isinstance(item, str):
                cleaned = item.lower().removeprefix("mailto:").strip()
                if _is_valid_email(cleaned):
                    emails.add(cleaned)

    phone_val = data.get("telephone")
    if isinstance(phone_val, str):
        normalized = _normalize_phone(phone_val)
        if normalized:
            phones.add(normalized)
    elif isinstance(phone_val, list):
        for item in phone_val:
            if isinstance(item, str):
                normalized = _normalize_phone(item)
                if normalized:
                    phones.add(normalized)

    same_as = data.get("sameAs")
    if isinstance(same_as, str):
        absolute = urljoin(base_url or "", same_as) if base_url else same_as
        normalized = _normalize_social_url(absolute)
        if normalized:
            social.add(normalized)
    elif isinstance(same_as, list):
        for item in same_as:
            if isinstance(item, str):
                absolute = urljoin(base_url or "", item) if base_url else item
                normalized = _normalize_social_url(absolute)
                if normalized:
                    social.add(normalized)

    graph = data.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            _collect_json_ld_contacts(item, emails, phones, social, base_url=base_url)

    for key, value in data.items():
        if key in {"email", "telephone", "sameAs", "@graph"}:
            continue
        if isinstance(value, (dict, list)):
            _collect_json_ld_contacts(value, emails, phones, social, base_url=base_url)


def _strip_svg(html: str) -> str:
    """Remove SVG blocks that often contain coordinate false phone matches."""
    return re.sub(r"<svg[^>]*>.*?</svg>", "", html, flags=re.IGNORECASE | re.DOTALL)


def _is_placeholder_phone(digits: str) -> bool:
    """True for obvious form-placeholder / fake / analytics-like numbers."""
    if digits == "9999999999":
        return True
    if len(set(digits)) == 1:
        return True
    if len(digits) == 10 and digits[:3] == digits[3:6] == digits[6:]:
        return True
    # Google Maps / CID style fragments and sequential junk.
    if digits.startswith(("688", "202612", "000", "111", "123")):
        return True
    if digits in {"1234567890", "0123456789", "9876543210"}:
        return True
    return False


def _normalize_phone(raw: str) -> str | None:
    """Normalize phone text; accept US NANP and international E.164-style numbers."""
    cleaned = re.sub(r"[\u2013\u2014]", "-", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    has_plus = cleaned.lstrip().startswith("+")
    digits = re.sub(r"\D", "", cleaned)
    if not digits:
        return None

    if len(digits) < 7 or len(digits) > 15:
        return None

    # US / NANP: 10 digits or 11 starting with 1
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
        has_plus = False
    if len(digits) == 10 and digits[0] in "23456789" and digits[3] in "23456789":
        if _is_placeholder_phone(digits):
            return None
        # Reject area codes that are clearly not NANP (e.g. 000-style already handled).
        area = int(digits[:3])
        if area < 200:
            return None
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"

    # International: keep E.164-ish form when clearly international
    if has_plus and 8 <= len(digits) <= 15:
        check = digits[1:] if len(digits) == 11 and digits.startswith("1") else digits
        if len(check) == 10 and _is_placeholder_phone(check):
            return None
        return f"+{digits}"

    # tel:/JSON-LD without + but longer than NANP (e.g. UK 11 digits)
    if 11 <= len(digits) <= 15 and not digits.startswith("1"):
        if _is_placeholder_phone(digits):
            return None
        return f"+{digits}"

    return None
