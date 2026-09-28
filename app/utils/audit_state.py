"""Audit state serialization helpers."""

from __future__ import annotations

import copy
from typing import Any

from app.agents.state import AuditState


def serialize_audit_state(state: AuditState) -> dict[str, Any]:
    """Return a JSON-safe copy of audit state without large HTML payloads."""
    data = copy.deepcopy(dict(state))
    crawl_data = data.get("crawl_data")
    if isinstance(crawl_data, dict):
        pages = crawl_data.get("pages")
        if isinstance(pages, list):
            for page in pages:
                if isinstance(page, dict) and "raw_html" in page:
                    page.pop("raw_html", None)
    return data
