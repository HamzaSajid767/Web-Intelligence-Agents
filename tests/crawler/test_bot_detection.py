"""Bot protection detection tests."""

import pytest

from app.crawler.bot_detection import BotDetectionReason, BotProtectionDetector
from app.crawler.models import BackendName, PageFetchResult


@pytest.fixture
def detector() -> BotProtectionDetector:
    return BotProtectionDetector(min_html_length=500)


def test_http_403_detected(detector: BotProtectionDetector) -> None:
    result = PageFetchResult(
        url="https://example.com",
        status_code=403,
        success=False,
        html="<html></html>",
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is True
    assert analysis.reason == BotDetectionReason.HTTP_403


def test_http_429_detected(detector: BotProtectionDetector) -> None:
    result = PageFetchResult(
        url="https://example.com",
        status_code=429,
        success=False,
        html="rate limited",
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is True
    assert analysis.reason == BotDetectionReason.HTTP_429


def test_cloudflare_signature(detector: BotProtectionDetector) -> None:
    result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><body>Checking your browser before accessing...</body></html>",
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is True
    assert analysis.reason == BotDetectionReason.CLOUDFLARE


def test_captcha_signature(detector: BotProtectionDetector) -> None:
    result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><body><div class='g-recaptcha'></div></body></html>",
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is True
    assert analysis.reason == BotDetectionReason.CAPTCHA


def test_captcha_on_full_page_not_bot(detector: BotProtectionDetector) -> None:
    body = (
        "<html><head><title>HVAC Company</title></head><body>"
        "<div class='g-recaptcha'></div>"
        + ("HVAC services and heating repair. " * 50)
        + "</body></html>"
    )
    result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html=body,
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is False


def test_empty_body_on_success_status(detector: BotProtectionDetector) -> None:
    result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=False,
        html="",
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is True
    assert analysis.reason == BotDetectionReason.EMPTY_BODY


def test_fetch_failure_not_bot(detector: BotProtectionDetector) -> None:
    result = PageFetchResult(
        url="https://example.com",
        status_code=None,
        success=False,
        html="",
        backend_used=BackendName.COLLY,
        error="All connection attempts failed (is colly-sidecar running?)",
    )
    analysis = detector.analyze(result)
    assert analysis.detected is False


def test_noscript_tag_not_bot(detector: BotProtectionDetector) -> None:
    body = (
        "<html><head><title>With Pride HVAC</title></head><body>"
        "<noscript>Please enable JavaScript for maps.</noscript>"
        + ("HVAC services and heating repair. " * 50)
        + "</body></html>"
    )
    result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html=body,
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is False


def test_html_too_short(detector: BotProtectionDetector) -> None:
    result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html="<html><body>Hi</body></html>",
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is True
    assert analysis.reason == BotDetectionReason.HTML_TOO_SHORT


def test_challenge_platform_on_full_page_not_bot(detector: BotProtectionDetector) -> None:
    body = (
        "<html><head><title>212 HVAC Brooklyn</title></head><body>"
        "<script src='https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/scripts/'></script>"
        + ("HVAC heating and cooling services. " * 200)
        + "<a href='tel:9176335959'>(917) 633-5959</a></body></html>"
    )
    result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html=body,
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is False


def test_clean_page_not_detected(detector: BotProtectionDetector) -> None:
    body = "<html><head><title>Example</title></head><body>" + ("content " * 200) + "</body></html>"
    result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html=body,
        backend_used=BackendName.COLLY,
    )
    analysis = detector.analyze(result)
    assert analysis.detected is False
