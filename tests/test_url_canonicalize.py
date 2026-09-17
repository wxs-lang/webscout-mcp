"""Tests for URL canonicalization."""

from __future__ import annotations

import pytest

from webscout_mcp.url_canonicalize import canonicalize_url


def test_fragment_dropped():
    assert canonicalize_url("https://example.com/page#section") == "https://example.com/page"


def test_scheme_and_host_lowercased():
    assert canonicalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"


def test_tracking_params_removed():
    url = "https://example.com/p?utm_source=a&utm_medium=b&fbclid=xyz&id=keep"
    out = canonicalize_url(url)
    assert "utm_source" not in out
    assert "utm_medium" not in out
    assert "fbclid" not in out
    assert "id=keep" in out


def test_business_query_preserved():
    url = "https://example.com/search?q=hello&page=2"
    out = canonicalize_url(url)
    assert "q=hello" in out
    assert "page=2" in out


def test_auth_url_kept_intact():
    # Credentials in netloc must not be stripped — rewriting auth URLs
    # would break callers.
    url = "https://user:pass@example.com/p?utm_source=x"
    out = canonicalize_url(url)
    assert "user:pass@" in out
    assert "utm_source" not in out


def test_port_preserved():
    assert canonicalize_url("http://example.com:8080/p") == "http://example.com:8080/p"


def test_empty_and_garbage():
    assert canonicalize_url("") == ""
    # Garbage should not raise.
    canonicalize_url("not a url at all")


def test_duplicate_urls_collapse():
    a = canonicalize_url("https://Example.com/A?utm_source=x#top")
    b = canonicalize_url("https://example.com/A")
    assert a == b


def test_different_paths_not_merged():
    a = canonicalize_url("https://example.com/a")
    b = canonicalize_url("https://example.com/b")
    assert a != b
