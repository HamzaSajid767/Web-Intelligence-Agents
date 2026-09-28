"""Audit service unit tests."""

import pytest

from app.services.audit_service import AuditService


def test_validate_url_accepts_https():
    """Valid HTTPS URLs should pass validation and normalize identity form."""
    url = AuditService.validate_url("https://example.com")
    assert url == "https://example.com/"


def test_validate_url_rejects_invalid():
    """Invalid URLs should raise ValueError."""
    with pytest.raises(ValueError, match="http or https"):
        AuditService.validate_url("ftp://example.com")

    with pytest.raises(ValueError, match="valid domain"):
        AuditService.validate_url("https://")
