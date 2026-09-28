"""Tests for site validity gating."""

from app.analysis.site_validity import assess_site_validity, is_soft_404_page


def test_wix_connect_domain_invalid() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "title": "ConnectYourDomain Error",
            "clean_text": "This domain isn't connected to a website on Wix yet.",
            "success": True,
        }
    ]
    result = assess_site_validity(pages)
    assert result.is_valid is False
    assert result.reason


def test_parked_domain_invalid() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "title": "Domain for Sale",
            "clean_text": "This domain is parked. Buy this domain today.",
            "success": True,
        }
    ]
    result = assess_site_validity(pages)
    assert result.is_valid is False


def test_empty_site_invalid() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "title": "Home",
            "clean_text": "Hi",
            "success": True,
        }
    ]
    result = assess_site_validity(pages)
    assert result.is_valid is False


def test_healthy_multi_page_valid() -> None:
    body = (
        "Acme Accounting helps local businesses with bookkeeping, payroll, "
        "and year-end tax preparation. Contact our team for a consultation "
        "about fractional CFO services and monthly close support."
    )
    pages = [
        {
            "url": "https://example.com/",
            "title": "Acme Accounting",
            "clean_text": body,
            "success": True,
            "headings": [{"level": "h1", "text": "Acme Accounting"}],
        },
        {
            "url": "https://example.com/services",
            "title": "Services",
            "clean_text": body + " We also offer audit support.",
            "success": True,
        },
    ]
    result = assess_site_validity(pages)
    assert result.is_valid is True
    assert result.usable_page_count >= 1


def test_soft_404_detection() -> None:
    page = {
        "url": "https://example.com/missing",
        "title": "Page Not Found",
        "clean_text": "Sorry, the page you requested cannot be found.",
        "success": True,
    }
    assert is_soft_404_page(page) is True
