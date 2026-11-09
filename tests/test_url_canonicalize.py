"""Tests for URL canonicalization."""

from __future__ import annotations

import pytest

from webscout_mcp.url_canonicalize import canonical_url_key, canonicalize_url


def test_fragment_dropped():
    assert canonical_url_key("https://example.com/page#section") == "https://example.com/page"


def test_scheme_and_host_lowercased():
    assert canonical_url_key("HTTPS://Example.COM/Path") == "https://example.com/Path"


def test_tracking_params_removed():
    url = "https://example.com/p?utm_source=a&utm_medium=b&fbclid=xyz&id=keep"
    out = canonical_url_key(url)
    assert "utm_source" not in out
    assert "utm_medium" not in out
    assert "fbclid" not in out
    assert "id=keep" in out


def test_tracking_param_case_insensitive():
    out = canonical_url_key("https://example.com/?UTM_SOURCE=a&FBclid=x")
    assert "utm_source" not in out
    assert "fbclid" not in out


def test_business_query_preserved():
    url = "https://example.com/search?q=hello&page=2"
    out = canonical_url_key(url)
    assert "q=hello" in out
    assert "page=2" in out


# --- credentials separation (P0-3) ----------------------------------------


def test_canonical_key_strips_credentials():
    """Identity must not carry user:pass@."""
    out = canonical_url_key("https://user:pass@example.com/a")
    assert "user" not in out
    assert "pass" not in out
    assert "@" not in out
    assert out.startswith("https://example.com/a")


def test_original_request_url_unchanged():
    """canonical_url_key never rewrites the request URL; the caller must
    keep the original string for actual fetches."""
    original = "https://user:pass@example.com/p?utm_source=x"
    canon = canonical_url_key(original)
    # The canonical form is a derived identity, NOT the original request.
    assert canon != original
    # But it still points at the same host/path.
    assert "example.com/p" in canon


# --- signed / ambiguous URLs (P0-4) --------------------------------------


def test_signed_query_param_preserved():
    """AWS-style signed URLs must not be altered."""
    url = "https://example.com/file?X-Amz-Signature=abc%2Fdef&X-Amz-Credential=a%2Fb"
    out = canonical_url_key(url)
    assert "X-Amz-Signature" in out
    assert "X-Amz-Credential" in out


def test_percent_encoding_preserved():
    url = "https://example.com/s?name=a%20b&q=%2Fhello%2F"
    out = canonical_url_key(url)
    assert "a%20b" in out or "a+b" in out


def test_duplicate_query_keys_preserved():
    out = canonical_url_key("https://example.com/s?tag=a&tag=b")
    assert "tag=a" in out
    assert "tag=b" in out


def test_blank_query_value_preserved():
    out = canonical_url_key("https://example.com/s?flag=")
    assert "flag=" in out


# --- ambiguous params kept (P0-5) ----------------------------------------


def test_ref_params_preserved():
    """ref / ref_src / ref_url are ambiguous — keep them."""
    out = canonical_url_key("https://example.com/p?ref=newsletter&ref_src=twitter")
    assert "ref=newsletter" in out
    assert "ref_src=twitter" in out


# --- IPv6 (P0-6) ----------------------------------------------------------


def test_ipv6_no_port():
    out = canonical_url_key("http://[2001:db8::1]/p")
    assert out == "http://[2001:db8::1]/p"


def test_ipv6_with_port():
    out = canonical_url_key("http://[2001:db8::1]:8080/p")
    assert out == "http://[2001:db8::1]:8080/p"


def test_ipv4_kept():
    out = canonical_url_key("http://1.2.3.4:8080/p")
    assert out == "http://1.2.3.4:8080/p"


def test_hostname_with_port():
    assert canonical_url_key("http://example.com:8080/p") == "http://example.com:8080/p"


# --- misc -----------------------------------------------------------------


def test_empty_and_garbage():
    assert canonical_url_key("") == ""
    canonical_url_key("not a url at all")


def test_duplicate_urls_collapse():
    a = canonical_url_key("https://Example.com/A?utm_source=x#top")
    b = canonical_url_key("https://example.com/A")
    assert a == b


def test_different_paths_not_merged():
    a = canonical_url_key("https://example.com/a")
    b = canonical_url_key("https://example.com/b")
    assert a != b


def test_canonicalize_url_is_alias():
    assert canonicalize_url("https://example.com/x?utm_source=a") == canonical_url_key(
        "https://example.com/x?utm_source=a"
    )
