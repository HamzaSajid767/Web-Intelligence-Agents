"""Tests for shared URL identity normalization."""

import pytest

from app.core.url_identity import (
    choose_canonical_url,
    lookup_keys,
    normalize_identity_url,
    same_org_host,
    validate_http_url,
)


def test_normalize_adds_root_slash_and_lowercases():
    assert normalize_identity_url("https://Example.COM") == "https://example.com/"
    assert normalize_identity_url("https://example.com/") == "https://example.com/"


def test_normalize_strips_default_port_fragment_and_tracking():
    assert (
        normalize_identity_url("https://example.com:443/path?utm_source=x&keep=1#frag")
        == "https://example.com/path?keep=1"
    )
    assert normalize_identity_url("http://example.com:80/") == "http://example.com/"


def test_lookup_keys_include_www_and_legacy_no_slash():
    keys = lookup_keys("https://www.example.com")
    assert "https://www.example.com/" in keys
    assert "https://example.com/" in keys
    assert "https://example.com" in keys


def test_same_org_host_www_insensitive():
    assert same_org_host("https://www.a.com/", "https://a.com/about")
    assert not same_org_host("https://a.com/", "https://b.com/")


def test_choose_canonical_prefers_same_org_html_canonical():
    chosen = choose_canonical_url(
        "https://hayes-cpa.com",
        final_url="https://hayes.cpa/",
        html_canonical="https://hayes.cpa/home",
    )
    assert chosen == "https://hayes.cpa/home"


def test_choose_canonical_ignores_cross_org_html_canonical():
    chosen = choose_canonical_url(
        "https://hayes-cpa.com",
        final_url="https://hayes.cpa/",
        html_canonical="https://unrelated.example/page",
    )
    assert chosen == "https://hayes.cpa/"


def test_choose_canonical_uses_final_when_no_html():
    assert (
        choose_canonical_url("https://hayes-cpa.com", final_url="https://hayes.cpa")
        == "https://hayes.cpa/"
    )


def test_validate_rejects_bad_schemes():
    with pytest.raises(ValueError, match="http or https"):
        validate_http_url("ftp://example.com")
    with pytest.raises(ValueError, match="valid domain"):
        validate_http_url("https://")


def test_validate_repairs_missing_scheme_slashes():
    assert validate_http_url("https:www.example.com") == "https://www.example.com"
    assert (
        normalize_identity_url("https:msha.ke/nasrjewelersmn")
        == "https://msha.ke/nasrjewelersmn"
    )
