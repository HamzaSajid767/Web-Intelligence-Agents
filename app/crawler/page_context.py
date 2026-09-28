"""Build LLM-facing page context from crawled page data."""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings

_PAGE_SEPARATOR = "\n---\n"
_HEADING_LEVELS = {"h1", "h2", "h3"}
_META_KEYS = (
    "description",
    "keywords",
    "og:title",
    "og:description",
    "canonical",
    "robots",
    "has_schema",
    "schema_types",
)
_THIN_CONTENT_THRESHOLD = 100


def build_page_context(
    pages: list[dict[str, Any]],
    *,
    max_pages: int = 5,
    max_chars_per_page: int = 2500,
) -> str:
    """Format crawled pages into structured text for downstream LLM agents."""
    if not pages:
        return "No page content"

    sections: list[str] = []
    for page in pages[:max_pages]:
        section = _format_page(page, max_chars_per_page=max_chars_per_page)
        if section:
            sections.append(section)

    return _PAGE_SEPARATOR.join(sections) if sections else "No page content"


def build_agent_page_context(pages: list[dict[str, Any]]) -> str:
    """Build a smaller page context sized for local Ollama inference."""
    settings = get_settings()
    return build_page_context(
        pages,
        max_pages=settings.agent_context_max_pages,
        max_chars_per_page=settings.agent_context_max_chars_per_page,
    )


def build_downstream_context(
    crawl_data: dict[str, Any],
    pages: list[dict[str, Any]] | None = None,
) -> str:
    """Prefer crawler analysis + compact page snippets for later agents.

    Full pages/contacts remain in crawl_data / DB; this only shrinks LLM prompts.
    """
    pages = pages if pages is not None else list(crawl_data.get("pages") or [])
    analysis = crawl_data.get("analysis") or {}
    sections: list[str] = []
    if analysis:
        sections.append("Crawler analysis:")
        sections.append(json.dumps(analysis, indent=2, default=str))
    # Compact page signal strip — not full body text.
    compact = build_page_context(pages, max_pages=2, max_chars_per_page=400)
    if compact and compact != "No page content":
        sections.append("Compact page signals:")
        sections.append(compact)
    if sections:
        return "\n".join(sections)
    return build_agent_page_context(pages)


def _format_page(page: dict[str, Any], *, max_chars_per_page: int) -> str:
    lines: list[str] = []

    url = page.get("url") or ""
    if url:
        lines.append(f"URL: {url}")

    title = page.get("title")
    if title:
        lines.append(f"Title: {title}")

    meta_line = _format_metadata(page.get("metadata") or {})
    if meta_line:
        lines.append(f"Meta: {meta_line}")

    headings_line = _format_headings(page.get("headings") or [])
    if headings_line:
        lines.append(f"Headings: {headings_line}")

    image_stats_line = _format_image_stats(page.get("image_stats") or {})
    if image_stats_line:
        lines.append(f"Images: {image_stats_line}")

    chatbot_line = _format_chatbot_signals(page.get("chatbot_signals") or {})
    if chatbot_line:
        lines.append(f"Chatbot: {chatbot_line}")

    content = _select_content(page)
    if content:
        lines.append(f"Content:\n{_truncate(content, max_chars_per_page)}")

    return "\n".join(lines)


def _format_metadata(metadata: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in _META_KEYS:
        value = metadata.get(key)
        if value is True:
            parts.append(f"{key}=yes")
        elif value is False:
            parts.append(f"{key}=no")
        elif isinstance(value, list):
            if value:
                parts.append(f"{key}={', '.join(str(item) for item in value)}")
        elif value:
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def _format_image_stats(image_stats: dict[str, Any]) -> str:
    total = image_stats.get("total_images", 0)
    if not total:
        return ""
    without_alt = image_stats.get("images_without_alt", 0)
    with_alt = image_stats.get("images_with_alt", 0)
    return f"{total} total, {with_alt} with alt, {without_alt} without alt"


def _format_chatbot_signals(chatbot_signals: dict[str, Any]) -> str:
    parts: list[str] = []
    script_urls = chatbot_signals.get("script_urls") or []
    launcher_labels = chatbot_signals.get("launcher_labels") or []
    welcome_messages = chatbot_signals.get("welcome_messages") or []

    if script_urls or launcher_labels:
        parts.append("widget detected")
    if launcher_labels:
        parts.append(f'launcher="{launcher_labels[0]}"')
    if welcome_messages:
        parts.append(f'welcome="{welcome_messages[0][:80]}"')
    return "; ".join(parts)


def _format_headings(headings: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for heading in headings:
        level = str(heading.get("level", "")).lower()
        text = heading.get("text", "")
        if level in _HEADING_LEVELS and text:
            parts.append(f"{level}: {text}")
    return " | ".join(parts)


def _select_content(page: dict[str, Any]) -> str:
    clean_text = (page.get("clean_text") or "").strip()
    markdown = (page.get("markdown") or "").strip()

    if len(clean_text) >= _THIN_CONTENT_THRESHOLD:
        return clean_text
    if clean_text and markdown:
        return f"{clean_text}\n\n{markdown}"
    return clean_text or markdown


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
