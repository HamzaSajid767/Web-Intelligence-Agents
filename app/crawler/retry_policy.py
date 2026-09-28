"""Retry classification and backoff helpers for crawler fetches."""

from app.crawler.bot_detection import (
    BotDetectionReason,
    BotProtectionDetector,
    is_dns_failure,
    is_infrastructure_failure,
)
from app.crawler.models import PageFetchResult


TRANSIENT_STATUS_CODES = frozenset({502, 503, 504})
TERMINAL_STATUS_CODES = frozenset({403, 429})
TERMINAL_BOT_REASONS = frozenset(
    {
        BotDetectionReason.HTTP_403,
        BotDetectionReason.HTTP_429,
        BotDetectionReason.CLOUDFLARE,
        BotDetectionReason.CAPTCHA,
        BotDetectionReason.JS_CHALLENGE,
        BotDetectionReason.PROTECTION_PAGE,
        BotDetectionReason.EMPTY_BODY,
        BotDetectionReason.HTML_TOO_SHORT,
        BotDetectionReason.TLS_FINGERPRINT,
    }
)


def is_ssl_certificate_error(result: PageFetchResult) -> bool:
    """True for expired/invalid TLS certificates (not worth blindly retrying)."""
    if not result.error:
        return False
    lowered = result.error.lower()
    return any(
        marker in lowered
        for marker in (
            "certificate verify failed",
            "certificate has expired",
            "certificate_verify_failed",
            "sslcertverificationerror",
        )
    )


def is_transient_error(result: PageFetchResult) -> bool:
    """Return True when Colly should be retried."""
    if is_infrastructure_failure(result):
        return False

    # Expired/invalid certs are persistent until the site fixes them.
    if is_ssl_certificate_error(result):
        return False

    if is_dns_failure(result):
        return True

    if result.error:
        lowered = result.error.lower()
        transient_markers = (
            "timeout",
            "timed out",
            "dns",
            "ssl",
            "502",
            "503",
            "504",
        )
        if any(marker in lowered for marker in transient_markers):
            return True

    if result.status_code in TRANSIENT_STATUS_CODES:
        return True

    return False


def is_terminal_failure(
    result: PageFetchResult,
    detector: BotProtectionDetector,
) -> bool:
    """Return True when Colly retries should stop and fallback may be used."""
    if is_infrastructure_failure(result):
        return True

    if result.status_code in TERMINAL_STATUS_CODES:
        return True

    bot = detector.analyze(result)
    if bot.detected and bot.reason in TERMINAL_BOT_REASONS:
        return True

    if result.status_code is not None and result.status_code >= 400 and not is_transient_error(result):
        return True

    return False


def should_retry_colly(
    result: PageFetchResult,
    detector: BotProtectionDetector,
) -> bool:
    """Determine if another Colly attempt is warranted."""
    if result.success and not detector.analyze(result).detected:
        return False
    if is_infrastructure_failure(result):
        return False
    if is_terminal_failure(result, detector):
        return False
    return is_transient_error(result)


def compute_backoff_seconds(base: float, attempt: int) -> float:
    """Exponential backoff delay for retry attempt (1-indexed)."""
    return base * (2 ** (attempt - 1))
