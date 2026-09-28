"""Tests for page context builder."""

from app.crawler.page_context import build_page_context


def test_build_page_context_includes_metadata_and_headings() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "title": "Home",
            "metadata": {"description": "HVAC services in NYC", "og:title": "Example HVAC"},
            "headings": [
                {"level": "h1", "text": "Welcome"},
                {"level": "h2", "text": "Our Services"},
                {"level": "h4", "text": "Ignored"},
            ],
            "clean_text": "We provide heating and cooling services.",
            "backend_used": "colly",
        }
    ]

    context = build_page_context(pages)

    assert "URL: https://example.com/" in context
    assert "Title: Home" in context
    assert "description=HVAC services in NYC" in context
    assert "h1: Welcome" in context
    assert "h2: Our Services" in context
    assert "h4: Ignored" not in context
    assert "We provide heating and cooling services." in context


def test_build_page_context_caps_per_page_chars() -> None:
    pages = [{"url": "https://example.com/", "clean_text": "x" * 5000}]

    context = build_page_context(pages, max_chars_per_page=100)

    assert context.endswith("...")
    assert len(context) < 5000


def test_build_page_context_limits_page_count() -> None:
    pages = [
        {"url": f"https://example.com/{i}", "clean_text": f"page {i}"}
        for i in range(10)
    ]

    context = build_page_context(pages, max_pages=2)

    assert "page 0" in context
    assert "page 1" in context
    assert "page 2" not in context


def test_build_page_context_falls_back_to_markdown() -> None:
    pages = [
        {
            "url": "https://example.com/",
            "clean_text": "Short",
            "markdown": "# Services\n\nFull markdown body for the page.",
        }
    ]

    context = build_page_context(pages)

    assert "Short" in context
    assert "Full markdown body for the page." in context


def test_build_page_context_empty_pages() -> None:
    assert build_page_context([]) == "No page content"


def test_build_downstream_context_prefers_analysis() -> None:
    from app.crawler.page_context import build_downstream_context

    crawl_data = {
        "analysis": {"summary": "HVAC company", "primary_topics": ["AC"]},
        "pages": [
            {
                "url": "https://example.com/",
                "title": "Home",
                "clean_text": "Welcome " * 50,
                "metadata": {},
                "headings": [],
            }
        ],
    }
    context = build_downstream_context(crawl_data)
    assert "Crawler analysis:" in context
    assert "HVAC company" in context
    assert "Compact page signals:" in context


def test_build_agent_page_context_uses_smaller_limits(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("AGENT_CONTEXT_MAX_PAGES", "1")
    monkeypatch.setenv("AGENT_CONTEXT_MAX_CHARS_PER_PAGE", "50")

    from app.crawler.page_context import build_agent_page_context

    pages = [
        {"url": "https://example.com/1", "clean_text": "a" * 200},
        {"url": "https://example.com/2", "clean_text": "page two"},
    ]
    context = build_agent_page_context(pages)

    assert "example.com/1" in context
    assert "example.com/2" not in context
    assert context.endswith("...")
    get_settings.cache_clear()
