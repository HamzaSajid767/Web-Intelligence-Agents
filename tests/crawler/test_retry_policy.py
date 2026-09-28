"""Retry policy tests."""

from app.crawler.bot_detection import BotProtectionDetector
from app.crawler.models import BackendName, PageFetchResult
from app.crawler.retry_policy import (
    compute_backoff_seconds,
    is_terminal_failure,
    is_transient_error,
    should_retry_colly,
)


def test_transient_timeout_error() -> None:
    result = PageFetchResult(
        url="https://example.com",
        success=False,
        error="Connection timeout",
        backend_used=BackendName.COLLY,
    )
    assert is_transient_error(result) is True


def test_transient_503() -> None:
    result = PageFetchResult(
        url="https://example.com",
        status_code=503,
        success=False,
        backend_used=BackendName.COLLY,
    )
    assert is_transient_error(result) is True


def test_terminal_403() -> None:
    detector = BotProtectionDetector()
    result = PageFetchResult(
        url="https://example.com",
        status_code=403,
        success=False,
        html="forbidden",
        backend_used=BackendName.COLLY,
    )
    assert is_terminal_failure(result, detector) is True
    assert should_retry_colly(result, detector) is False


def test_infrastructure_failure_is_not_retried() -> None:
    detector = BotProtectionDetector()
    result = PageFetchResult(
        url="https://example.com",
        success=False,
        error="All connection attempts failed: Connection refused",
        backend_used=BackendName.COLLY,
    )
    assert is_transient_error(result) is False
    assert is_terminal_failure(result, detector) is True
    assert should_retry_colly(result, detector) is False


def test_dns_failure_is_retried() -> None:
    detector = BotProtectionDetector()
    result = PageFetchResult(
        url="https://example.com",
        success=False,
        error="[Errno 11001] getaddrinfo failed",
        backend_used=BackendName.COLLY,
    )
    assert is_transient_error(result) is True
    assert is_terminal_failure(result, detector) is False
    assert should_retry_colly(result, detector) is True


def test_ssl_certificate_error_is_not_retried() -> None:
    detector = BotProtectionDetector()
    result = PageFetchResult(
        url="https://example.com",
        success=False,
        error="[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired",
        backend_used=BackendName.HTTP,
    )
    assert is_transient_error(result) is False
    assert should_retry_colly(result, detector) is False


def test_backoff_exponential() -> None:
    assert compute_backoff_seconds(2.0, 1) == 2.0
    assert compute_backoff_seconds(2.0, 2) == 4.0
    assert compute_backoff_seconds(2.0, 3) == 8.0
