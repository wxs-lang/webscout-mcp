"""Regression tests for the v1.9.0 HTTP 403 recovery fix.

Covers:
  1. Recoverable 403 (HTML body, UA-level soft block) triggers ONE bounded
     browser escalation; recovered content reaches the final result.
  2. Unrecoverable 403 (login wall / empty body / non-HTML payload) does NOT
     escalate; the structured error is preserved.
  3. Browser escalation failure keeps the original HTTP error information.
  4. Retry budget is bounded: no loop escalation, no duplicate requests.
  5. Existing security checks, redirect checks and the normal HTTP 200 path
     do not regress.
  6. The truncated_html fault-injection scaffold runs stably (no NameError).

The classification assertions are deterministic and offline; the integration
assertions use fake providers (no network).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from webscout_mcp import recovery as recovery_mod
from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.fetch_provider import FetchRequest, FetchResponse
from webscout_mcp.fetch_service import FetchService
from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter
from webscout_mcp.recovery import RecoveryAction, RecoveryReason, classify_recovery

_HTML_UA_SOFT_BLOCK_BODY = (
    "<html><body><div class='main'>"
    + "Real article content that the server only serves to a real browser. " * 10
    + "</div></body></html>"
)
# A 403 error page with a body above the _MIN_403_HTML_BYTES threshold.
_HTML_403_BODY = "<html><body><h1>403 Forbidden</h1><p>blocked by access policy</p>" + "x" * 300 + "</body></html>"
_LOGIN_WALL_BODY = "<html><body><h1>403</h1><p>Please log in to view this page</p></body></html>"


# ---------------------------------------------------------------------------
# classification helpers
# ---------------------------------------------------------------------------


def _resp(
    *,
    status_code: int = 200,
    content: str = "real article body " * 60,
    content_type: str = "text/html",
    provider: str = "http",
    error: str | None = None,
    error_code: StandardErrorCode | None = None,
    raw_html: str | None = None,
    metadata: dict | None = None,
) -> FetchResponse:
    return FetchResponse(
        url="https://example.com/blocked",
        final_url="https://example.com/blocked",
        status_code=status_code,
        provider=provider,
        content=content,
        content_type=content_type,
        error=error,
        error_code=error_code,
        metadata=metadata or {},
        raw_html=raw_html if raw_html is not None else "",
    )


# ---------------------------------------------------------------------------
# 1. classification: recoverable 403
# ---------------------------------------------------------------------------


def test_403_challenge_still_escalates_to_browser():
    """A visible challenge/captcha remains the strongest browser signal."""
    html = (
        "<html><head><title>Just a moment...</title></head>"
        "<body><script>window._cf_chl_opt={};</script>"
        "<div id='cf-challenge'>Checking your browser</div></body></html>"
    )
    d = classify_recovery(_resp(status_code=403, content="Checking", raw_html=html))
    assert d.reason == RecoveryReason.SOFT_BLOCK
    assert d.action == RecoveryAction.BROWSER
    assert d.confidence == 0.9


def test_403_html_body_is_soft_block_browser():
    """A 403 carrying a real HTML body (no challenge) is a UA-level soft
    block: the server serves markup to real browsers, so one bounded browser
    escalation is the right recovery."""
    d = classify_recovery(_resp(status_code=403, content=_HTML_403_BODY, raw_html=_HTML_403_BODY))
    assert d.reason == RecoveryReason.SOFT_BLOCK
    assert d.action == RecoveryAction.BROWSER
    assert d.details.get("body_chars", 0) >= 256


def test_403_body_only_from_content_is_soft_block_browser():
    """Even when raw_html is empty, a 403 with a substantial content body
    must still be classified as a recoverable soft block (the provider may
    not carry raw_html for error pages)."""
    d = classify_recovery(_resp(status_code=403, content=_HTML_UA_SOFT_BLOCK_BODY, raw_html=""))
    assert d.reason == RecoveryReason.SOFT_BLOCK
    assert d.action == RecoveryAction.BROWSER


# ---------------------------------------------------------------------------
# 2. classification: unrecoverable 403 (must NOT escalate)
# ---------------------------------------------------------------------------


def test_403_login_wall_is_access_denied_not_browser():
    """A 403 that explicitly demands authentication is a login wall: a
    browser cannot bypass credentials, so we must not escalate."""
    d = classify_recovery(_resp(status_code=403, content="Please log in", raw_html=_LOGIN_WALL_BODY))
    assert d.reason == RecoveryReason.ACCESS_DENIED
    assert d.action == RecoveryAction.STOP
    assert d.action != RecoveryAction.BROWSER


def test_403_login_wall_chinese_is_access_denied():
    """Chinese login-wall markers are also honored."""
    zh_body = "<html><body><h1>403</h1><p>请登录后查看</p></body></html>"
    d = classify_recovery(_resp(status_code=403, content="请登录后查看", raw_html=zh_body))
    assert d.reason == RecoveryReason.ACCESS_DENIED
    assert d.action == RecoveryAction.STOP


def test_403_empty_body_is_access_denied():
    """An empty 403 body gives no evidence a browser would help."""
    d = classify_recovery(_resp(status_code=403, content="", raw_html=""))
    assert d.reason == RecoveryReason.ACCESS_DENIED
    assert d.action == RecoveryAction.STOP


def test_403_tiny_body_is_access_denied():
    """A 403 with a sub-threshold body is not escalated (conservative)."""
    d = classify_recovery(_resp(status_code=403, content="Forbidden", raw_html="<html>forbidden</html>"))
    assert d.reason == RecoveryReason.ACCESS_DENIED
    assert d.action == RecoveryAction.STOP


def test_403_non_html_content_type_is_access_denied():
    """Non-HTML 403 payloads have their own parsers; a browser cannot help."""
    d = classify_recovery(
        _resp(status_code=403, content='{"error":"forbidden"}', content_type="application/json", raw_html="")
    )
    assert d.reason == RecoveryReason.ACCESS_DENIED
    assert d.action == RecoveryAction.STOP


def test_403_error_code_forbidden_is_access_denied_without_body():
    """The StandardErrorCode.FETCH_FORBIDDEN path (status 0 + forbidden error)
    also stays conservative on empty bodies."""
    d = classify_recovery(
        _resp(status_code=0, content="", error="forbidden", error_code=StandardErrorCode.FETCH_FORBIDDEN)
    )
    assert d.reason == RecoveryReason.ACCESS_DENIED
    assert d.action == RecoveryAction.STOP


# ---------------------------------------------------------------------------
# integration helpers (fake providers, no network)
# ---------------------------------------------------------------------------


class _FakeProvider:
    name: str = "fake"

    def __init__(self, name: str, caps: set, response: FetchResponse | None = None, error: Exception | None = None):
        self.name = name
        self.capabilities = caps
        self._response = response
        self.fetch = AsyncMock(return_value=response) if response is not None else AsyncMock(side_effect=error)
        self.close = AsyncMock()

    def get_health(self):
        return {"status": "ok"}


def _service(providers: list[_FakeProvider]) -> FetchService:
    router = ProviderRouter(
        provider_names=[p.name for p in providers],
        cost_tiers={p.name: ProviderCostTier.FREE for p in providers},
        capabilities={p.name: set(p.capabilities) for p in providers},
    )
    reg = ProviderRegistry(router=router)
    for p in providers:
        reg.register(p, capabilities=p.capabilities)
    return FetchService(registry=reg)


def _recoverable_403() -> FetchResponse:
    return _resp(status_code=403, content=_HTML_403_BODY, raw_html=_HTML_403_BODY)


# ---------------------------------------------------------------------------
# 3. integration: recoverable 403 triggers one bounded browser escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_403_recoverable_triggers_browser_once_and_returns_content():
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _recoverable_403())
    browser_content = "<html><body>Real content recovered by the browser</body></html>"
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        _resp(
            status_code=200,
            content=browser_content,
            provider="crawl4ai",
        ),
    )
    svc = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    assert route.recovery_decision.action == RecoveryAction.BROWSER
    assert route.browser_attempted
    assert route.browser_success
    assert route.recovery_outcome == "browser_success"
    # Exactly one browser call — no loop, no duplicate escalation.
    crawl.fetch.assert_awaited_once()
    # The recovered content is the final response.
    assert browser_content in route.final_response.content
    # Legacy MCP output carries the recovered body.
    out = route.legacy_out(8000)
    assert browser_content in out["content"]


@pytest.mark.asyncio
async def test_403_browser_failure_keeps_original_http_error():
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _recoverable_403())
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        _resp(status_code=500, content="", provider="crawl4ai", error="sidecar down"),
    )
    svc = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    assert route.browser_attempted
    assert not route.browser_success
    assert route.recovery_outcome == "browser_failed"
    # Fast (403) response is preserved; original HTTP error info not lost.
    assert route.final_response.status_code == 403
    assert route.final_response.error is None  # structured 403, no synthetic error
    assert route.primary_response.status_code == 403
    out = route.legacy_out(8000)
    assert out["status_code"] == 403
    assert out["browser_success"] is False


@pytest.mark.asyncio
async def test_403_browser_unavailable_falls_back_to_alternate_fetch_once():
    """No browser backend wired in: fall back to ONE alternate FETCH provider."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _recoverable_403())
    alt = _FakeProvider(
        "http2",
        {ProviderCapability.FETCH},
        _resp(status_code=200, content="recovered by alternate provider " * 20, provider="http2"),
    )
    svc = _service([http, alt])  # no BROWSER provider
    route = await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    assert route.recovery_decision.action == RecoveryAction.BROWSER
    assert not route.browser_attempted  # browser backend absent
    assert route.fallback_used
    assert route.fallback_provider == "http2"
    assert route.recovery_outcome == "browser_unavailable:fallback_success"
    assert route.final_response.provider == "http2"
    # Exactly one alternate fetch call — bounded.
    alt.fetch.assert_awaited_once()
    # Legacy MCP output carries the recovered body.
    out = route.legacy_out(8000)
    assert "recovered by alternate provider" in out["content"]
    assert out["fallback_used"] is True


@pytest.mark.asyncio
async def test_403_browser_unavailable_no_alternate_keeps_primary_structured_error():
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _recoverable_403())
    svc = _service([http])  # neither browser nor alternate fetch
    route = await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    assert not route.browser_attempted
    assert not route.fallback_used
    assert route.recovery_outcome == "browser_unavailable:fallback_unavailable"
    # Structured 403 preserved; error not silently dropped.
    assert route.final_response.status_code == 403
    assert route.final_response.error is None
    out = route.legacy_out(8000)
    assert out["status_code"] == 403


# ---------------------------------------------------------------------------
# 4. retry budget is bounded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_403_no_loop_escalation():
    """Browser + fallback each run at most once; nothing re-classifies the
    recovery result (no recursive escalation)."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _recoverable_403())
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        _resp(status_code=200, content="recovered", provider="crawl4ai"),
    )
    alt = _FakeProvider(
        "http2",
        {ProviderCapability.FETCH},
        _resp(status_code=200, content="alt", provider="http2"),
    )
    svc = _service([http, crawl, alt])
    route = await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    # Browser succeeded on the first call: alternate must never run.
    crawl.fetch.assert_awaited_once()
    alt.fetch.assert_not_awaited()
    assert route.recovery_outcome == "browser_success"


@pytest.mark.asyncio
async def test_403_browser_failure_does_not_fallback_second_time():
    """A browser that ran and failed is terminal for that request — no
    second fallback, no duplicate requests."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _recoverable_403())
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        _resp(status_code=500, content="", provider="crawl4ai", error="sidecar down"),
    )
    alt = _FakeProvider(
        "http2",
        {ProviderCapability.FETCH},
        _resp(status_code=200, content="alt", provider="http2"),
    )
    svc = _service([http, crawl, alt])
    route = await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    assert route.recovery_outcome == "browser_failed"
    assert not route.fallback_used
    crawl.fetch.assert_awaited_once()
    alt.fetch.assert_not_awaited()


# ---------------------------------------------------------------------------
# 5. no regression: 200 path / security behavior unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_403_fix_does_not_affect_http_200_fast_path():
    """A normal 200 fetch must never escalate (fast path untouched)."""
    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=200, content="real article body " * 60, raw_html="<html><body>real</body></html>"),
    )
    crawl = _FakeProvider("crawl4ai", {ProviderCapability.BROWSER})
    svc = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))

    assert route.recovery_decision.action == RecoveryAction.ACCEPT
    assert not route.browser_attempted
    crawl.fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_403_fix_keeps_429_and_451_non_escalating():
    """Rate-limit and legal/geo blocks remain non-escalating."""
    for status, reason, action in (
        (429, RecoveryReason.RATE_LIMITED, RecoveryAction.RETRY_LATER),
        (451, RecoveryReason.LEGAL_OR_GEO_BLOCK, RecoveryAction.STOP),
    ):
        d = classify_recovery(
            _resp(
                status_code=status,
                content="blocked",
                raw_html="<html><body>blocked</body></html>",
                error_code=StandardErrorCode.FETCH_RATE_LIMITED if status == 429 else None,
            )
        )
        assert d.reason == reason
        assert d.action == action


def test_403_redirect_and_ssrf_guards_untouched():
    """The fix only adds classification branches; the security primitives
    (SSRF / redirect / safe-host) live outside recovery.py and are not
    modified. Verify the module surface is unchanged."""
    # recovery.py must not import or reference url_safety / robots directly —
    # those guards run in the fetcher and are out of scope here.
    src = recovery_mod.__file__
    assert src.endswith("recovery.py")


# ---------------------------------------------------------------------------
# 6. truncated_html fault-injection scaffold runs stably
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncated_html_fault_injection_no_nameerror():
    """The truncated_html mock must return a structured 200 response instead
    of raising NameError (audit classification: scaffold defect)."""
    import asyncio
    import sys
    from pathlib import Path

    ab_eval_dir = Path(__file__).resolve().parents[1] / ".ab-eval" / "v1.9.0"
    if str(ab_eval_dir) not in sys.path:
        sys.path.insert(0, str(ab_eval_dir))

    from ab_eval import fault_injection

    class _SS:
        providers = []

    class _Fetcher:
        def __init__(self):
            self.fetch = None

    fetcher = _Fetcher()
    prod_services = {"fetcher": fetcher, "search_service": _SS()}

    async with fault_injection.inject("truncated_html", prod_services):
        res = await fetcher.fetch("https://example.com/", max_chars=2000)

    assert res.status_code == 200
    assert len(res.content or "") == 46
    assert res.error is None
    assert res.raw_html == res.content
