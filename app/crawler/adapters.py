"""Adapters converting backend fetch results to audit page models."""

from typing import Any

from app.crawler.html_processor import process_html
from app.crawler.models import MAX_CLEAN_TEXT_LENGTH, MAX_RAW_HTML_LENGTH, PageData, PageFetchResult


def sanitize_db_text(value: str | None) -> str | None:
    """Remove NUL bytes that BSON/string storage rejects."""
    if value is None:
        return None
    return value.replace("\x00", "")


def _sanitize_page_strings(page_data: dict[str, Any]) -> None:
    """Strip NUL characters from page text fields in place."""
    for key in ("title", "clean_text", "raw_html", "markdown"):
        if isinstance(page_data.get(key), str):
            page_data[key] = sanitize_db_text(page_data[key])

    metadata = page_data.get("metadata")
    if isinstance(metadata, dict):
        page_data["metadata"] = {
            key: sanitize_db_text(val) if isinstance(val, str) else val
            for key, val in metadata.items()
        }

    for heading in page_data.get("headings") or []:
        if isinstance(heading, dict) and isinstance(heading.get("text"), str):
            heading["text"] = sanitize_db_text(heading["text"])

    for link in page_data.get("links") or []:
        if isinstance(link, dict):
            if isinstance(link.get("text"), str):
                link["text"] = sanitize_db_text(link["text"])
            if isinstance(link.get("url"), str):
                link["url"] = sanitize_db_text(link["url"])


def fetch_result_to_page_data(fetch_result: PageFetchResult) -> PageData:
    """Convert a unified fetch result into pipeline PageData."""
    page_dict: dict[str, Any] = {
        "url": fetch_result.url,
        "status_code": fetch_result.status_code,
        "success": fetch_result.success,
        "markdown": fetch_result.markdown,
        "backend_used": fetch_result.backend_used,
        "response_time_ms": fetch_result.response_time_ms,
    }

    if fetch_result.html:
        processed = process_html(fetch_result.html, fetch_result.url)
        page_dict.update(
            {
                "title": processed.get("title") or fetch_result.title,
                "raw_html": processed.get("raw_html"),
                "clean_text": processed.get("clean_text") or fetch_result.text,
                "metadata": {**processed.get("metadata", {}), **fetch_result.metadata},
                "headings": processed.get("headings", []),
                "links": processed.get("links") or fetch_result.links,
                "image_stats": processed.get("image_stats", {}),
                "chatbot_signals": processed.get("chatbot_signals", {}),
            }
        )
    else:
        page_dict.update(
            {
                "title": fetch_result.title,
                "raw_html": None,
                "clean_text": fetch_result.text or fetch_result.markdown,
                "metadata": fetch_result.metadata,
                "headings": [],
                "links": fetch_result.links,
                "image_stats": {},
                "chatbot_signals": {},
            }
        )

    return PageData(**cap_page_data(page_dict))


def cap_page_data(page_data: dict[str, Any]) -> dict[str, Any]:
    """Limit stored text size per page and sanitize for database storage."""
    _sanitize_page_strings(page_data)
    clean_text = page_data.get("clean_text")
    if clean_text and len(clean_text) > MAX_CLEAN_TEXT_LENGTH:
        page_data["clean_text"] = clean_text[:MAX_CLEAN_TEXT_LENGTH]
    raw_html = page_data.get("raw_html")
    if raw_html and len(raw_html) > MAX_RAW_HTML_LENGTH:
        page_data["raw_html"] = raw_html[:MAX_RAW_HTML_LENGTH]
    markdown = page_data.get("markdown")
    if markdown and len(markdown) > MAX_CLEAN_TEXT_LENGTH:
        page_data["markdown"] = markdown[:MAX_CLEAN_TEXT_LENGTH]
    return page_data
