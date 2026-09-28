"""Domain exceptions for the audit pipeline."""

from __future__ import annotations

import uuid


class InvalidSiteError(Exception):
    """Raised when a crawl yields an unusable / parked / error website."""

    def __init__(
        self,
        message: str,
        *,
        audit_id: uuid.UUID | None = None,
        website_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.audit_id = audit_id
        self.website_url = website_url
