"""Page fetch result adapter tests."""

from app.crawler.adapters import cap_page_data, fetch_result_to_page_data
from app.crawler.models import BackendName, MAX_CLEAN_TEXT_LENGTH, PageFetchResult


def test_fetch_result_html_to_page_data() -> None:
    html = (
        "<html><head><title>Test Page</title>"
        '<meta name="description" content="Desc"></head>'
        '<body><h1>Hello</h1><a href="/about">About</a></body></html>'
    )
    fetch_result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        html=html,
        backend_used=BackendName.COLLY,
        response_time_ms=100.0,
    )
    page = fetch_result_to_page_data(fetch_result)
    assert page.title == "Test Page"
    assert page.raw_html == html
    assert "Hello" in (page.clean_text or "")
    assert page.backend_used == BackendName.COLLY
    assert len(page.links) >= 1


def test_fetch_result_markdown_only() -> None:
    fetch_result = PageFetchResult(
        url="https://example.com",
        status_code=200,
        success=True,
        markdown="# Hello\n\nWorld",
        backend_used=BackendName.WEBCLAW,
        response_time_ms=200.0,
    )
    page = fetch_result_to_page_data(fetch_result)
    assert page.clean_text == "# Hello\n\nWorld"
    assert page.markdown == "# Hello\n\nWorld"
    assert page.backend_used == BackendName.WEBCLAW


def test_cap_page_data() -> None:
    capped = cap_page_data({"clean_text": "x" * (MAX_CLEAN_TEXT_LENGTH + 100)})
    assert len(capped["clean_text"]) == MAX_CLEAN_TEXT_LENGTH


def test_cap_page_data_strips_nul_bytes() -> None:
    capped = cap_page_data(
        {
            "title": "Hello\x00World",
            "clean_text": "line\x00one",
            "raw_html": "<p>\x00</p>",
            "metadata": {"description": "desc\x00"},
            "headings": [{"level": "h1", "text": "Hi\x00"}],
            "links": [{"url": "https://example.com", "text": "Go\x00"}],
        }
    )
    assert capped["title"] == "HelloWorld"
    assert capped["clean_text"] == "lineone"
    assert capped["raw_html"] == "<p></p>"
    assert capped["metadata"]["description"] == "desc"
    assert capped["headings"][0]["text"] == "Hi"
    assert capped["links"][0]["text"] == "Go"
