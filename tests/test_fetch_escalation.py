"""Tests for fetch escalation decision rules (v1.2.2)."""

from __future__ import annotations

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.fetch_escalation import (
    EscalationReason,
    should_escalate_to_browser,
)
from webscout_mcp.fetch_provider import FetchResponse


def _resp(
    *,
    status_code: int = 200,
    content: str = "real article body " * 50,
    content_type: str = "text/html",
    error: str | None = None,
    raw_html: str | None = None,
    content_quality: str | None = None,
) -> FetchResponse:
    meta = {}
    if raw_html is not None:
        meta["raw_html"] = raw_html
    if content_quality is not None:
        meta["content_quality"] = content_quality
    return FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=status_code,
        provider="http",
        content=content,
        content_type=content_type,
        error=error,
        metadata=meta,
    )


def test_200_healthy_page_does_not_escalate():
    d = should_escalate_to_browser(_resp(content="a" * 500, raw_html="<html><body>real</body></html>"))
    assert d.escalate is False


def test_403_escalates_as_soft_block():
    d = should_escalate_to_browser(_resp(status_code=403, content="", raw_html=""))
    assert d.escalate is True
    assert d.reason_code == EscalationReason.SOFT_BLOCK


def test_451_never_escalates():
    d = should_escalate_to_browser(_resp(status_code=451))
    assert d.escalate is False


def test_429_never_escalates():
    d = should_escalate_to_browser(_resp(status_code=429, error="Too many requests"))
    assert d.escalate is False


def test_401_never_escalates():
    d = should_escalate_to_browser(_resp(status_code=401, error="Unauthorized"))
    assert d.escalate is False


def test_challenge_page_escalates():
    html = (
        "<html><head><title>Just a moment...</title></head><body>Checking your browser before accessing</body></html>"
    )
    d = should_escalate_to_browser(_resp(content="", raw_html=html))
    assert d.escalate is True
    assert d.reason_code == EscalationReason.SOFT_BLOCK


def test_js_placeholder_escalates():
    html = "<html><body>Please enable JavaScript to continue</body></html>"
    d = should_escalate_to_browser(_resp(content="", raw_html=html))
    assert d.escalate is True
    assert d.reason_code == EscalationReason.JS_REQUIRED


def test_short_text_with_heavy_html_escalates_as_low_density():
    # Tiny extracted text, but large HTML full of <script> -> SPA signature.
    scripts = "<script>var x=1;</script>" * 200
    html = f"<html><body>{scripts}<noscript>empty</noscript></body></html>"
    d = should_escalate_to_browser(_resp(content="", raw_html=html))
    assert d.escalate is True
    assert d.reason_code == EscalationReason.LOW_CONTENT_DENSITY


def test_short_text_but_small_html_does_not_escalate():
    # A genuinely small page (short text AND small HTML) should not trigger.
    d = should_escalate_to_browser(_resp(content="hi", raw_html="<html>hi</html>"))
    assert d.escalate is False


def test_low_quality_with_non_trivial_html_escalates():
    big = "<p>filler</p>" * 200
    d = should_escalate_to_browser(_resp(content="x", raw_html=f"<html>{big}</html>", content_quality="low"))
    assert d.escalate is True
    assert d.reason_code == EscalationReason.LOW_QUALITY


def test_pdf_content_type_never_escalates():
    d = should_escalate_to_browser(_resp(content="", content_type="application/pdf", raw_html="garbage"))
    assert d.escalate is False


def test_json_content_type_never_escalates():
    d = should_escalate_to_browser(_resp(content="", content_type="application/json", raw_html="[]"))
    assert d.escalate is False


def test_dns_error_never_escalates():
    d = should_escalate_to_browser(_resp(error="DNS lookup failed"))
    assert d.escalate is False


def test_5xx_never_escalates():
    d = should_escalate_to_browser(_resp(status_code=503, error="overloaded"))
    assert d.escalate is False


def test_decision_has_serializable_dict():
    d = should_escalate_to_browser(_resp(status_code=403))
    out = d.to_dict()
    assert out["escalate"] is True
    assert out["reason_code"] == "SOFT_BLOCK"
    assert 0 <= out["confidence"] <= 1
