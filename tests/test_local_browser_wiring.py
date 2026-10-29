"""The browser capability: wiring contract and the escalation guard.

Two things needed pinning after wiring the local browser.

Wiring: LocalBrowserBackend must satisfy the same interface Crawl4AI does, because
server.py and eval_services.py treat them interchangeably. `is_available` is a
property there, so it must be one here - my first version made it a coroutine and
the same call site would have broken.

Guard: escalation must not fire when the reason is a missing extractor. Measured
consequence of getting that wrong - every page escalated, P50 557ms -> 3865ms.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from webscout_mcp.fetch_provider import BrowserFetchProvider, FetchResponse
from webscout_mcp.local_browser_backend import LocalBrowserBackend
from webscout_mcp.recovery import RecoveryAction, RecoveryReason, classify_recovery

# --- Interface parity with the sidecar backend -------------------------


def test_local_backend_is_a_browser_fetch_provider():
    assert issubclass(LocalBrowserBackend, BrowserFetchProvider)


def test_is_available_is_a_property_not_a_coroutine():
    """server.py does `if backend.is_available:` in synchronous wiring."""
    attr = inspect.getattr_static(LocalBrowserBackend, "is_available")
    assert isinstance(attr, property), "must be a property; async wiring would break"


def test_is_configured_reflects_the_dependency():
    backend = LocalBrowserBackend()
    assert isinstance(backend.is_configured(), bool)


def test_fetch_is_a_coroutine():
    assert inspect.iscoroutinefunction(LocalBrowserBackend.fetch)


def test_health_reports_the_reason(monkeypatch):
    backend = LocalBrowserBackend()
    monkeypatch.setattr(backend, "_unavailable_reason", "browser cannot launch")
    result = asyncio.run(backend.health())
    assert result["available"] is False
    assert "cannot launch" in result["reason"]


def test_known_unavailable_returns_a_typed_failure_without_launching():
    """A missing browser must cost one attempt, not one per request."""
    backend = LocalBrowserBackend()
    backend._unavailable_reason = "browser cannot launch"
    resp = asyncio.run(backend.fetch(type("R", (), {"url": "https://example.test/"})()))
    assert isinstance(resp, FetchResponse)
    assert resp.status_code == 0
    assert resp.error and "launch" in resp.error
    asyncio.run(backend.close())


# --- The escalation guard ---------------------------------------------


def _resp(content: str, *, extracted: bool, extraction_status, content_type="text/html; charset=utf-8"):
    return FetchResponse(
        url="https://example.test/",
        final_url="https://example.test/",
        status_code=200,
        provider="http",
        content=content,
        content_type=content_type,
        extracted=extracted,
        extraction_status=extraction_status,
        raw_html="<html><body>" + content + "</body></html>",
    )


def test_missing_extractor_does_not_escalate():
    """Rendering cannot fix a missing extractor - the browser returns markup too."""
    d = classify_recovery(
        _resp("<!DOCTYPE html><html><div id=root></div></html>", extracted=False, extraction_status="unavailable")
    )
    assert d.action is not RecoveryAction.BROWSER, "escalating on 'unavailable' costs seconds and cannot succeed"


def test_empty_extraction_does_escalate():
    """An extractor ran and found nothing; a browser may render real content."""
    d = classify_recovery(
        _resp("<!DOCTYPE html><html><div id=root></div></html>", extracted=False, extraction_status="empty")
    )
    assert d.reason is RecoveryReason.LOW_CONTENT_DENSITY
    assert d.action is RecoveryAction.BROWSER


def test_successfully_extracted_page_does_not_escalate():
    """Extraction worked; the length-based judgements must behave as before."""
    d = classify_recovery(_resp("# Title\n\n" + "real text. " * 400, extracted=True, extraction_status="ok"))
    assert d.action in (RecoveryAction.ACCEPT, RecoveryAction.CONTINUE_CONTENT)


def test_truncated_real_text_still_reports_continue():
    """Guards the guard: OUTPUT_TRUNCATED must survive for genuinely extracted text."""
    resp = _resp("# Title\n\n" + "y" * 9000, extracted=True, extraction_status="ok")
    resp.metadata = {"truncated_by_output_limit": True, "pre_limit_content_chars": 40000}
    d = classify_recovery(resp)
    assert d.reason is RecoveryReason.OUTPUT_TRUNCATED


def test_plain_text_response_is_not_treated_as_unextracted_html():
    """content_type gates it: a .txt body has no markup to extract."""
    d = classify_recovery(_resp("plain text" * 500, extracted=False, extraction_status=None, content_type="text/plain"))
    assert d.action is not RecoveryAction.BROWSER
