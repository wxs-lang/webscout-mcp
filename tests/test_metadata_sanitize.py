"""Tests for metadata sanitization."""

from __future__ import annotations

import pytest

from webscout_mcp.metadata_sanitize import is_sensitive_key, sanitize_metadata
from webscout_mcp.web_result import WebResult


def test_cookie_keys_removed():
    out = sanitize_metadata(
        {
            "set_cookie": "session=abc",
            "Set-Cookie": "x=1",
            "cookies": "a=1",
            "normal": "keep",
        }
    )
    assert "set_cookie" not in out
    assert "Set-Cookie" not in out
    assert "cookies" not in out
    assert out["normal"] == "keep"


def test_authorization_keys_removed():
    out = sanitize_metadata(
        {
            "Authorization": "Bearer secret",
            "authorization": "lower",
            "proxy-authorization": "x",
        }
    )
    assert "Authorization" not in out
    assert "authorization" not in out
    assert "proxy-authorization" not in out


def test_token_variants_removed():
    out = sanitize_metadata(
        {
            "access_token": "a",
            "refresh_token": "r",
            "auth_token": "t",
            "session_token": "s",
            "user_token": "u",
        }
    )
    assert out == {}


def test_api_key_variants_removed():
    out = sanitize_metadata(
        {
            "api_key": "k",
            "apikey": "k",
            "x-api-key": "k",
            "X-API-Key": "k",
        }
    )
    assert out == {}


def test_password_variants_removed():
    out = sanitize_metadata(
        {
            "password": "p",
            "user_password": "p",
            "passwd": "p",
            "client_secret": "s",
        }
    )
    assert out == {}


def test_normal_metadata_kept():
    out = sanitize_metadata(
        {
            "status_code": 200,
            "latency_ms": 12.3,
            "cached": False,
            "kind": "fetch",
        }
    )
    assert out == {
        "status_code": 200,
        "latency_ms": 12.3,
        "cached": False,
        "kind": "fetch",
    }


def test_none_metadata():
    assert sanitize_metadata(None) == {}
    assert sanitize_metadata({}) == {}


def test_does_not_mutate_input():
    inp = {"password": "p", "ok": 1}
    sanitize_metadata(inp)
    assert inp == {"password": "p", "ok": 1}


def test_webresult_to_dict_second_layer():
    """Even if someone constructs WebResult directly with sensitive keys,
    to_dict strips them."""
    r = WebResult(
        url="u",
        metadata={
            "set_cookie": "s",
            "Authorization": "Bearer x",
            "access_token": "t",
            "normal_field": "safe",
        },
    )
    d = r.to_dict()
    assert "set_cookie" not in d["metadata"]
    assert "Authorization" not in d["metadata"]
    assert "access_token" not in d["metadata"]
    assert d["metadata"]["normal_field"] == "safe"
