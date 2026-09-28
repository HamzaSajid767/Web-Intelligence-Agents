"""Bot protection and anti-scraping detection heuristics."""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.crawler.models import PageFetchResult

# Sidecar / local connectivity failures: fail-fast to the next backend.
INFRASTRUCTURE_ERROR_MARKERS: tuple[str, ...] = (
    "connection refused",
    "connection error",
    "connection failed",
    "all connection attempts failed",
    "connect error",
    "connect timeout",
    "failed to connect",
    "network unreachable",
    "colly_url",
    "webclaw",
    "no connection could be made",
)

# Target-host DNS flakes are retriable (common under Windows worker load).
DNS_ERROR_MARKERS: tuple[str, ...] = (
    "getaddrinfo failed",
    "name or service not known",
    "temporary failure in name resolution",
    "nodename nor servname provided",
    "dns lookup failed",
)


class BotDetectionReason(StrEnum):
    """Reasons a page response is treated as bot-protected."""

    HTTP_403 = "http_403"
    HTTP_429 = "http_429"
    CLOUDFLARE = "cloudflare"
    CAPTCHA = "captcha"
    JS_CHALLENGE = "js_challenge"
    EMPTY_BODY = "empty_body"
    HTML_TOO_SHORT = "html_too_short"
    PROTECTION_PAGE = "protection_page"
    TLS_FINGERPRINT = "tls_fingerprint"


# Specific challenge phrases only — avoid broad tokens like "cloudflare" or "noscript"
# that appear on normal pages (CDN assets, standard HTML tags).
PROTECTION_SIGNATURES: dict[BotDetectionReason, tuple[str, ...]] = {
    BotDetectionReason.CLOUDFLARE: (
        "checking your browser",
        "just a moment...",
        "cf-browser-verification",
        "__cf_chl",
        "cf-challenge",
        "challenge-running",
    ),
    BotDetectionReason.CAPTCHA: (
        "g-recaptcha",
        "hcaptcha.com",
        "cf-turnstile",
        "recaptcha/api.js",
        "class=\"g-recaptcha\"",
    ),
    BotDetectionReason.PROTECTION_PAGE: (
        "datadome",
        "perimeterx",
        "/_incapsula_resource",
        "bot detection",
        "automated access is not allowed",
        "sgcaptcha",
        "/.well-known/sgcaptcha",
    ),
    BotDetectionReason.JS_CHALLENGE: (
        "enable javascript to continue",
        "javascript is required to view this page",
        "javascript is required to run",
        "javascript is disabled in your browser",
    ),
    BotDetectionReason.TLS_FINGERPRINT: (
        "tls fingerprint",
        "fingerprint blocking",
    ),
}

# Signatures that often appear on legitimate full pages (widgets, script URLs).
WEAK_SIGNATURES_ON_FULL_PAGE = frozenset(
    {
        BotDetectionReason.CAPTCHA,
        BotDetectionReason.JS_CHALLENGE,
    }
)
BLOCK_PAGE_TITLE_RE = re.compile(
    r"<title[^>]*>\s*(?:"
    r"just a moment\.\.\.|"
    r"access denied|"
    r"attention required|"
    r"please wait\.\.\.|"
    r"403 forbidden|"
    r"429 too many requests"
    r")\s*</title>",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BotDetectionResult:
    """Outcome of bot protection analysis."""

    detected: bool
    reason: BotDetectionReason | None = None
    details: str | None = None


def is_dns_failure(result: PageFetchResult) -> bool:
    """Return True when the error looks like a transient DNS resolution failure."""
    if result.success or not result.error:
        return False
    lowered = result.error.lower()
    return any(marker in lowered for marker in DNS_ERROR_MARKERS)


def is_infrastructure_failure(result: PageFetchResult) -> bool:
    """Return True when the fetch failed before a usable HTTP response.

    DNS errors are excluded here so callers can retry them; they remain
    detectable via :func:`is_dns_failure`.
    """
    if result.success:
        return False
    if result.html and len(result.html.strip()) > 0:
        return False
    if result.status_code is not None and result.status_code > 0:
        return False
    if is_dns_failure(result):
        return False
    if result.error:
        lowered = result.error.lower()
        return any(marker in lowered for marker in INFRASTRUCTURE_ERROR_MARKERS)
    return result.status_code is None


class BotProtectionDetector:
    """Detect bot protection from HTTP status and response body."""

    def __init__(self, min_html_length: int = 500) -> None:
        self.min_html_length = min_html_length

    def analyze(self, result: PageFetchResult) -> BotDetectionResult:
        """Analyze a fetch result for bot protection signals."""
        if is_infrastructure_failure(result):
            return BotDetectionResult(False)

        status = result.status_code
        if status == 403:
            return BotDetectionResult(True, BotDetectionReason.HTTP_403, "HTTP 403 Forbidden")
        if status == 429:
            return BotDetectionResult(True, BotDetectionReason.HTTP_429, "HTTP 429 Too Many Requests")

        body = (result.html or result.text or result.markdown or "").strip()
        if not body:
            if status is not None and 200 <= status < 400:
                return BotDetectionResult(
                    True,
                    BotDetectionReason.EMPTY_BODY,
                    "Empty response body on successful HTTP status",
                )
            return BotDetectionResult(False)

        body = self._strip_noscript(body)
        lowered = body.lower()
        if BLOCK_PAGE_TITLE_RE.search(body):
            return BotDetectionResult(
                True,
                BotDetectionReason.PROTECTION_PAGE,
                "Blocked page title detected",
            )

        for reason, signatures in PROTECTION_SIGNATURES.items():
            for signature in signatures:
                if signature not in lowered:
                    continue
                # Widgets/script URLs on otherwise normal pages (recaptcha, challenge-platform).
                if reason in WEAK_SIGNATURES_ON_FULL_PAGE and len(body) >= self.min_html_length:
                    continue
                return BotDetectionResult(True, reason, f"Matched signature: {signature}")

        if len(body) < self.min_html_length:
            return BotDetectionResult(
                True,
                BotDetectionReason.HTML_TOO_SHORT,
                f"Body length {len(body)} below threshold {self.min_html_length}",
            )

        if self._is_js_challenge_shell(lowered):
            return BotDetectionResult(
                True,
                BotDetectionReason.JS_CHALLENGE,
                "Minimal content shell without title",
            )

        return BotDetectionResult(False)

    @staticmethod
    def _strip_noscript(body: str) -> str:
        """Remove noscript blocks that commonly trigger false positives."""
        return re.sub(r"<noscript[^>]*>.*?</noscript>", "", body, flags=re.IGNORECASE | re.DOTALL)

    @staticmethod
    def _is_js_challenge_shell(lowered_body: str) -> bool:
        """Detect JS challenge pages with almost no visible content."""
        if "<title" in lowered_body:
            return False
        text_density = sum(1 for c in lowered_body if c.isalnum())
        return text_density < 80 and "challenge-platform" in lowered_body
