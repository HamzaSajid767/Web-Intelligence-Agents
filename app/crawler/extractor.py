"""HTML metadata and content extraction."""

import json
from typing import Any

from bs4 import BeautifulSoup


def extract_title(soup: BeautifulSoup) -> str | None:
    """Extract page title."""
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return str(og_title["content"]).strip()
    return None


def extract_metadata(soup: BeautifulSoup) -> dict[str, Any]:
    """Extract meta tags and Open Graph data."""
    metadata: dict[str, Any] = {}

    description = soup.find("meta", attrs={"name": "description"})
    if description and description.get("content"):
        metadata["description"] = str(description["content"]).strip()

    keywords = soup.find("meta", attrs={"name": "keywords"})
    if keywords and keywords.get("content"):
        metadata["keywords"] = str(keywords["content"]).strip()

    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        metadata["canonical"] = str(canonical["href"]).strip()

    robots = soup.find("meta", attrs={"name": "robots"})
    if robots and robots.get("content"):
        metadata["robots"] = str(robots["content"]).strip()

    for og_tag in soup.find_all("meta", property=lambda x: x and x.startswith("og:")):
        prop = og_tag.get("property", "")
        content = og_tag.get("content", "")
        if prop and content:
            metadata[prop] = str(content).strip()

    schema_types = _extract_schema_types(soup)
    metadata["has_schema"] = bool(schema_types)
    if schema_types:
        metadata["schema_types"] = schema_types

    return metadata


def _extract_schema_types(soup: BeautifulSoup) -> list[str]:
    """Extract @type values from JSON-LD script blocks."""
    schema_types: list[str] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        schema_types.extend(_collect_schema_types(data))
    return list(dict.fromkeys(schema_types))


def _collect_schema_types(data: Any) -> list[str]:
    """Recursively collect @type values from JSON-LD data."""
    types: list[str] = []
    if isinstance(data, dict):
        schema_type = data.get("@type")
        if schema_type:
            if isinstance(schema_type, list):
                types.extend(str(item) for item in schema_type)
            else:
                types.append(str(schema_type))
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                types.extend(_collect_schema_types(item))
    elif isinstance(data, list):
        for item in data:
            types.extend(_collect_schema_types(item))
    return types
