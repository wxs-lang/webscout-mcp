"""Tests for deterministic recovery classification (Phase 2.7B).

The classifier only recommends; it never executes recovery or changes
production routing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.recovery import RecoveryAction, RecoveryReason, classify_recovery


def _resp(
    *,
    status_code: int = 200,
    content: str = "real article body " * 60,
    content_type: str = "text/html",
    error: str | None = None,
    error_code: StandardErrorCode | None = None,
    retryable: bool = False,
    raw_html: str | None = None,
    metadata: dict | None = None,
) -> FetchResponse:
    return FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=status_code,
        provider="http",
        content=content,
        content_type=content_type,
        error=error,
        error_code=error_code,
        retryable=retryable,
        metadata=metadata or {},
        raw_html=raw_html if raw_html is not None else "",
    )


def test_output_truncated_recommends_continue():
    r = _resp(
        metadata={
            "truncated_by_output_limit": True,
            "pre_limit_content_chars": 40000,
            "returned_content_chars": 8038,
            "output_limit_chars": 8000,
            "omitted_chars": 32000,
        },
        raw_html="<html><body><article>" + "x" * 40000 + "</article></body></html>",
    )
    d = classify_recovery(r)
    assert d.reason == RecoveryReason.OUTPUT_TRUNCATED
    assert d.action == RecoveryAction.CONTINUE_CONTENT
    assert d.details["omitted_chars"] == 32000


def test_403_challenge_is_soft_block_browser():
    html = (
        "<html><head><title>Just a moment...</title></head>"
        "<body><script>window._cf_chl_opt={};</script>"
        "<div id='cf-challenge'>Checking your browser</div></body></html>"
    )
    d = classify_recovery(_resp(status_code=403, content="Checking", raw_html=html))
    assert d.reason == RecoveryReason.SOFT_BLOCK
    assert d.action == RecoveryAction.BROWSER


def test_plain_403_is_access_denied_not_browser():
    d = classify_recovery(_resp(status_code=403, content="Forbidden", raw_html="<html>forbidden</html>"))
    assert d.reason == RecoveryReason.ACCESS_DENIED
    assert d.action != RecoveryAction.BROWSER


def test_js_placeholder_is_js_required():
    html = "<html><body>Please enable JavaScript to continue.<noscript></noscript></body></html>"
    d = classify_recovery(_resp(content="Please enable JavaScript to continue.", raw_html=html))
    assert d.reason == RecoveryReason.JS_REQUIRED
    assert d.action == RecoveryAction.BROWSER


def test_short_text_heavy_scripts_is_low_density():
    html = "<html><head>" + "<script>" + "var x=1;" * 600 + "</script></head><body></body></html>"
    d = classify_recovery(_resp(content="x", raw_html=html))
    assert d.reason == RecoveryReason.LOW_CONTENT_DENSITY
    assert d.action == RecoveryAction.BROWSER


def test_low_quality_is_browser_recommendation():
    big = "<p>filler</p>" * 200
    d = classify_recovery(_resp(content="x", raw_html=f"<html>{big}</html>", metadata={"content_quality": "low"}))
    assert d.reason == RecoveryReason.LOW_QUALITY
    assert d.action == RecoveryAction.BROWSER


def test_429_is_rate_limited_retry_later():
    d = classify_recovery(
        _resp(status_code=429, error="Too many requests", error_code=StandardErrorCode.FETCH_RATE_LIMITED)
    )
    assert d.reason == RecoveryReason.RATE_LIMITED
    assert d.action == RecoveryAction.RETRY_LATER


def test_401_is_auth_required():
    d = classify_recovery(_resp(status_code=401, error="Unauthorized"))
    assert d.reason == RecoveryReason.AUTH_REQUIRED
    assert d.action == RecoveryAction.REQUIRE_AUTH


def test_407_is_auth_required():
    d = classify_recovery(_resp(status_code=407, error="Proxy Authentication Required"))
    assert d.reason == RecoveryReason.AUTH_REQUIRED


def test_451_is_legal_geo_stop():
    d = classify_recovery(_resp(status_code=451, error="Unavailable For Legal Reasons"))
    assert d.reason == RecoveryReason.LEGAL_OR_GEO_BLOCK
    assert d.action == RecoveryAction.STOP


def test_5xx_is_server_error_retry():
    d = classify_recovery(
        _resp(status_code=503, error="Service Unavailable", error_code=StandardErrorCode.FETCH_SERVER_ERROR)
    )
    assert d.reason == RecoveryReason.SERVER_ERROR
    assert d.action == RecoveryAction.RETRY


def test_dns_is_network_failure():
    d = classify_recovery(
        _resp(status_code=0, error="DNS resolution failed", error_code=StandardErrorCode.FETCH_DNS_ERROR)
    )
    assert d.reason == RecoveryReason.NETWORK_FAILURE
    assert d.action == RecoveryAction.RETRY


def test_connect_is_network_failure():
    d = classify_recovery(
        _resp(status_code=0, error="Connection refused", error_code=StandardErrorCode.FETCH_CONNECTION_ERROR)
    )
    assert d.reason == RecoveryReason.NETWORK_FAILURE


def test_timeout_is_retry():
    d = classify_recovery(_resp(status_code=0, error="request timed out", error_code=StandardErrorCode.FETCH_TIMEOUT))
    assert d.reason == RecoveryReason.TIMEOUT
    assert d.action == RecoveryAction.RETRY


def test_ssl_is_tls_failure():
    d = classify_recovery(
        _resp(status_code=0, error="SSL certificate verify failed", error_code=StandardErrorCode.FETCH_SSL_ERROR)
    )
    assert d.reason == RecoveryReason.TLS_FAILURE
    assert d.action == RecoveryAction.PROVIDER_FALLBACK


def test_pdf_not_browser():
    d = classify_recovery(_resp(content_type="application/pdf", content="%PDF-1.4 binary"))
    assert d.reason == RecoveryReason.UNSUPPORTED_CONTENT_TYPE
    assert d.action != RecoveryAction.BROWSER


def test_json_not_browser():
    d = classify_recovery(_resp(content_type="application/json", content='{"a":1}'))
    assert d.reason == RecoveryReason.UNSUPPORTED_CONTENT_TYPE


def test_image_not_browser():
    d = classify_recovery(_resp(content_type="image/png", content=""))
    assert d.reason == RecoveryReason.UNSUPPORTED_CONTENT_TYPE
    assert d.action != RecoveryAction.BROWSER


def test_example_style_complete_short_page():
    html = "<html><body><div><h1>Example Domain</h1><p>This domain is for use in examples.</p></div></body></html>"
    d = classify_recovery(_resp(content="Example Domain This domain is for use in examples.", raw_html=html))
    assert d.reason == RecoveryReason.COMPLETE_SHORT_PAGE
    assert d.action == RecoveryAction.ACCEPT


def test_full_page_complete_content():
    d = classify_recovery(
        _resp(content="y" * 5000, raw_html="<html><body><article>" + "y" * 5000 + "</article></body></html>")
    )
    assert d.reason == RecoveryReason.COMPLETE_CONTENT
    assert d.action == RecoveryAction.ACCEPT


def test_thin_shell_on_large_script_heavy_doc_is_ambiguous():
    # ~1085 extracted chars on a huge script-heavy doc: cannot prove complete.
    content = "loading " * 180  # ~1440 chars
    html = "<html><head>" + "<script>" + "var z=2;" * 3000 + "</script></head><body>" + content + "</body></html>"
    d = classify_recovery(_resp(content=content, raw_html=html))
    assert d.reason == RecoveryReason.AMBIGUOUS
    assert d.action == RecoveryAction.NONE


def test_empty_success_is_ambiguous():
    d = classify_recovery(_resp(content="   ", raw_html="<html></html>"))
    assert d.reason == RecoveryReason.AMBIGUOUS
    assert d.action == RecoveryAction.NONE


def test_truncation_uses_metadata_not_length_guess():
    # Content looks ~8000 but metadata explicitly says not truncated -> complete.
    r = _resp(
        content="w" * 8000,
        raw_html="<html><body><article>" + "w" * 8000 + "</article></body></html>",
        metadata={"truncated_by_output_limit": False},
    )
    d = classify_recovery(r)
    assert d.reason != RecoveryReason.OUTPUT_TRUNCATED


def test_no_raw_html_leak_in_details():
    r = _resp(
        metadata={
            "truncated_by_output_limit": True,
            "pre_limit_content_chars": 9000,
            "output_limit_chars": 8000,
            "omitted_chars": 1000,
        }
    )
    d = classify_recovery(r)
    dump = d.to_dict()
    assert "raw_html" not in dump["details"]
    assert all(isinstance(v, (int, float, str, bool, type(None))) for v in dump["details"].values())


def test_404_is_access_denied():
    d = classify_recovery(_resp(status_code=404, error="Not Found", error_code=StandardErrorCode.FETCH_NOT_FOUND))
    assert d.reason == RecoveryReason.ACCESS_DENIED
    assert d.action == RecoveryAction.STOP


def test_mcp_tool_count_unchanged():
    server = Path(__file__).resolve().parents[1] / "webscout_mcp" / "server.py"
    out = subprocess.run(
        [sys.executable, "-c", f"print(open(r'{server}').read().count('@mcp.tool'))"],
        capture_output=True,
        text=True,
    )
    assert int(out.stdout.strip()) == 11


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))
