"""Tests for the lightweight observability layer."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from webscout_mcp.observability import (
    get_observability_summary,
    record_escalation,
    record_fetch_attempt,
    record_ssrf_block,
    reset_for_tests,
    safe_host,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_for_tests()
    yield
    reset_for_tests()


# --- safe_host ------------------------------------------------------------


def test_safe_host_strips_query_and_path():
    assert safe_host("https://example.com/path?q=secret&token=abc") == "https://example.com"


def test_safe_host_strips_credentials():
    assert safe_host("https://user:pass@example.com/") == "https://example.com"


def test_safe_host_keeps_port():
    assert safe_host("http://localhost:8080/admin") == "http://localhost:8080"


def test_safe_host_handles_garbage():
    assert safe_host("not a url") == "invalid-url"


# --- record_fetch_attempt --------------------------------------------------


def test_record_fetch_attempt_counts_backends():
    record_fetch_attempt("fast-http", result="success", latency_ms=12.3)
    record_fetch_attempt("fast-http", result="success", latency_ms=20.0)
    record_fetch_attempt("fast-http", result="timeout", latency_ms=100.0)
    s = get_observability_summary()
    b = s["backends"]["fast-http"]
    assert b["calls"] == 3
    assert b["success"] == 2
    assert b["timeout"] == 1
    assert b["failure"] == 0


def test_p50_p95():
    for i in range(1, 11):
        record_fetch_attempt("fast-http", result="success", latency_ms=float(i))
    s = get_observability_summary()
    b = s["backends"]["fast-http"]
    # 1..10 median ~5.5, p95 ~9.5..10
    assert b["p50_ms"] >= 5.0
    assert b["p95_ms"] >= 9.0


def test_record_escalation_counts():
    record_escalation("JS_REQUIRED")
    record_escalation("JS_REQUIRED")
    record_escalation("HTTP_403")
    s = get_observability_summary()
    assert s["escalations"] == {"JS_REQUIRED": 2, "HTTP_403": 1}


def test_record_ssrf_block_counts():
    record_ssrf_block("loopback")
    record_ssrf_block("loopback")
    record_ssrf_block("metadata")
    s = get_observability_summary()
    assert s["ssrf_blocks"] == {"loopback": 2, "metadata": 1}


def test_summary_is_json_serialisable():
    record_fetch_attempt("crawl4ai", result="failure", latency_ms=500.0, reason="timeout")
    record_ssrf_block("private")
    s = get_observability_summary()
    # Should not raise.
    json.dumps(s)


# --- failure isolation ----------------------------------------------------


def test_record_failure_does_not_raise():
    """If record_fetch_attempt throws, the caller must not see it."""
    with patch("webscout_mcp.observability._BACKEND_BUCKETS", side_effect=RuntimeError("boom")):
        # Should not raise.
        record_fetch_attempt("fast-http", result="success", latency_ms=1.0)


def test_safe_host_never_returns_query_string():
    """Privacy regression: safe_host must not leak query strings."""
    url = "https://api.example.com/search?token=secret123&key=abc"
    out = safe_host(url)
    assert "token" not in out
    assert "secret123" not in out
    assert "abc" not in out
