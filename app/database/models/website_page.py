"""Website page embedded document."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.database.models.base import new_uuid


@dataclass
class WebsitePage:
    """Crawled page embedded on a website audit."""

    url: str
    id: uuid.UUID = field(default_factory=new_uuid)
    title: str | None = None
    raw_html: str | None = None
    clean_text: str | None = None
    metadata_json: dict[str, Any] | None = None
    headings_json: list[Any] | None = None
    links_json: list[Any] | None = None

    def to_document(self) -> dict:
        """Serialize to embedded MongoDB subdocument."""
        return {
            "id": str(self.id),
            "url": self.url,
            "title": self.title,
            "raw_html": self.raw_html,
            "clean_text": self.clean_text,
            "metadata": self.metadata_json,
            "headings": self.headings_json,
            "links": self.links_json,
        }

    @classmethod
    def from_document(cls, doc: dict) -> WebsitePage:
        """Deserialize from embedded MongoDB subdocument."""
        return cls(
            id=uuid.UUID(str(doc.get("id", new_uuid()))),
            url=doc["url"],
            title=doc.get("title"),
            raw_html=doc.get("raw_html"),
            clean_text=doc.get("clean_text"),
            metadata_json=doc.get("metadata"),
            headings_json=doc.get("headings"),
            links_json=doc.get("links"),
        )
