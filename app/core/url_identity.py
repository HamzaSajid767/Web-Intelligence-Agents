"""Shared URL identity normalization for audit uniqueness and crawl scope."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_QUERY_KEYS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
        "_ga",
    }
)

# Common scrape typo: "https:www.example.com" (missing "//").
_MISSING_SLASHES = re.compile(r"^(https?):(?!//)(.+)$", re.IGNORECASE)


def _repair_scheme_separator(url: str) -> str:
    """Insert missing ``://`` after http(s) when the next chars are not ``//``."""
    match = _MISSING_SLASHES.match(url)
    if not match:
        return url
    return f"{match.group(1).lower()}://{match.group(2)}"


def validate_http_url(url: str) -> str:
    """Validate that url is http(s) with a netloc; return stripped input."""
    if not url or not str(url).strip():
        raise ValueError("URL must include a valid domain")
    cleaned = _repair_scheme_separator(str(url).strip())
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL must use http or https scheme")
    if not parsed.netloc:
        raise ValueError("URL must include a valid domain")
    return cleaned


def _strip_default_port(netloc: str, scheme: str) -> str:
    host = netloc.lower()
    if scheme == "http" and host.endswith(":80"):
        return host[:-3]
    if scheme == "https" and host.endswith(":443"):
        return host[:-4]
    return host


def org_host(url_or_host: str) -> str:
    """Return host with www. stripped for same-organization comparisons."""
    if "://" in url_or_host:
        host = urlparse(url_or_host).netloc.lower()
    else:
        host = url_or_host.lower()
    host = host.split("@")[-1]
    return host.removeprefix("www.")


def same_org_host(base_url: str, target_url: str) -> bool:
    """True when hosts match ignoring www. prefix."""
    return org_host(base_url) == org_host(target_url)


def normalize_identity_url(url: str) -> str:
    """Normalize a URL to the canonical identity string form.

    Rules: lowercase scheme/host, strip default ports, drop fragment,
    strip tracking query keys, root path becomes ``/``.
    """
    validated = validate_http_url(url)
    parsed = urlparse(validated)
    scheme = parsed.scheme.lower()
    netloc = _strip_default_port(parsed.netloc, scheme)
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(query_pairs, doseq=True)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", query, ""))


def lookup_keys(url: str) -> list[str]:
    """Return equivalent identity strings for Mongo lookup (www / apex variants)."""
    identity = normalize_identity_url(url)
    parsed = urlparse(identity)
    host = parsed.netloc
    apex = host.removeprefix("www.")
    hosts = {host, apex, f"www.{apex}" if not host.startswith("www.") else host}
    keys: list[str] = []
    seen: set[str] = set()
    for h in hosts:
        candidate = urlunparse(
            (parsed.scheme, h, parsed.path, "", parsed.query, "")
        )
        if candidate not in seen:
            seen.add(candidate)
            keys.append(candidate)
        # Also include no-trailing-slash origin form for legacy docs.
        if parsed.path == "/" and not parsed.query:
            legacy = f"{parsed.scheme}://{h}"
            if legacy not in seen:
                seen.add(legacy)
                keys.append(legacy)
    return keys


def choose_canonical_url(
    submitted: str,
    final_url: str | None = None,
    html_canonical: str | None = None,
) -> str:
    """Choose the canonical identity URL after crawl resolution.

    Prefers same-org HTML canonical when present; otherwise final response URL;
    falls back to normalized submitted URL.
    """
    base = normalize_identity_url(submitted)
    resolved = normalize_identity_url(final_url) if final_url else base

    if html_canonical:
        try:
            html_norm = normalize_identity_url(html_canonical)
        except ValueError:
            return resolved
        # Prefer HTML canonical only when same organization as the resolved host.
        if same_org_host(resolved, html_norm) or same_org_host(base, html_norm):
            return html_norm
    return resolved
