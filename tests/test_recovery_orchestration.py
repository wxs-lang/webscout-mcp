"""Phase 2.7D — Unified Recovery Orchestration tests.

Asserts that ``classify_recovery`` / ``RecoveryDecision`` is the single
high-level decision source in FetchService: the low-level browser detector
runs once (inside the classifier), each RecoveryAction has one deterministic
execution outcome, there is no second retry loop, browser runs at most once,
provider fallback runs at most once, and the continuation fast path is
untouched.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from webscout_mcp import fetch_service as fs_mod
from webscout_mcp import recovery as recovery_mod
from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.fetch_provider import FetchRequest, FetchResponse
from webscout_mcp.fetch_service import FetchService
from webscout_mcp.observability import get_observability_summary, reset_for_tests
from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter
from webscout_mcp.recovery import RecoveryAction, RecoveryReason


class _Fake:
    def __init__(self, name, caps, response=None, error=None):
        self.name = name
        self.capabilities = caps
        self._response = response
        self.fetch = AsyncMock(return_value=response) if response is not None else AsyncMock(side_effect=error)
        self.close = AsyncMock()

    def get_health(self):
        return {"status": "ok"}


def _registry(providers):
    router = ProviderRouter(
        provider_names=[p.name for p in providers],
        cost_tiers={p.name: ProviderCostTier.FREE for p in providers},
        capabilities={p.name: set(p.capabilities) for p in providers},
    )
    reg = ProviderRegistry(router=router)
    for p in providers:
        reg.register(p, capabilities=p.capabilities)
    return reg, router


def _resp(**kw):
    kw.setdefault("url", "https://example.com")
    kw.setdefault("final_url", "https://example.com")
    kw.setdefault("status_code", 200)
    kw.setdefault("provider", "http")
    kw.setdefault("content", "real article body " * 60)
    kw.setdefault("content_type", "text/html")
    kw.setdefault("raw_html", "")
    return FetchResponse(**kw)


def _service(providers):
    reg, router = _registry(providers)
    return FetchService(registry=reg), reg, router


@pytest.fixture(autouse=True)
def _reset_obs():
    reset_for_tests()
    yield
    reset_for_tests()


def _browser(content="rendered real content", status=200, error=None):
    return _Fake(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        _resp(provider="crawl4ai", status_code=status, content=content, error=error),
    )


# --- single source of truth -------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_service_has_no_direct_browser_detector():
    """FetchService must not import/call should_escalate_to_browser directly."""
    assert not hasattr(fs_mod, "should_escalate_to_browser")


@pytest.mark.asyncio
async def test_browser_detector_runs_exactly_once_via_classifier(monkeypatch):
    html = "<html><body>Please enable JavaScript to continue.<noscript></noscript></body></html>"
    http = _Fake("http", {ProviderCapability.FETCH}, _resp(content="Please enable JavaScript.", raw_html=html))
    crawl = _browser()
    svc, _, _ = _service([http, crawl])

    calls = {"n": 0}
    orig = recovery_mod.should_escalate_to_browser

    def _count(resp):
        calls["n"] += 1
        return orig(resp)

    monkeypatch.setattr(recovery_mod, "should_escalate_to_browser", _count)
    route = await svc.fetch(FetchRequest(url="https://example.com"))

    assert calls["n"] == 1
    assert route.recovery_decision.reason == RecoveryReason.JS_REQUIRED
    assert route.recovery_decision.action == RecoveryAction.BROWSER
    assert crawl.fetch.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,reason",
    [
        (
            _resp(
                status_code=403,
                content="",
                raw_html="<html><body>cloudflare captcha please verify</body></html>",
            ),
            RecoveryReason.SOFT_BLOCK,
        ),
        (
            _resp(content="x", raw_html="<html><head>" + "<script>var x=1;</script>" * 600 + "</head></html>"),
            RecoveryReason.LOW_CONTENT_DENSITY,
        ),
        (
            _resp(
                content="x",
                raw_html="<html>" + "<p>filler</p>" * 200 + "</html>",
                metadata={"content_quality": "low"},
            ),
            RecoveryReason.LOW_QUALITY,
        ),
    ],
)
async def test_browser_reasons_invoke_browser_once(response, reason):
    http = _Fake("http", {ProviderCapability.FETCH}, response)
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.reason == reason
    assert route.recovery_decision.action == RecoveryAction.BROWSER
    assert route.browser_attempted
    assert route.browser_success
    assert crawl.fetch.await_count == 1
    assert route.final_response.provider == "crawl4ai"


# --- non-browser actions ----------------------------------------------------


@pytest.mark.asyncio
async def test_output_truncated_continues_no_browser():
    resp = _resp(
        metadata={
            "truncated_by_output_limit": True,
            "content_total_chars": 40000,
            "content_start_char": 0,
            "content_end_char": 8000,
            "has_more": True,
            "next_start_char": 8000,
            "remaining_chars": 32000,
            "pre_limit_content_chars": 40000,
            "returned_content_chars": 8000,
            "output_limit_chars": 8000,
        }
    )
    http = _Fake("http", {ProviderCapability.FETCH}, resp)
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.action == RecoveryAction.CONTINUE_CONTENT
    assert route.recovery_outcome == "continuation_ready"
    assert not route.browser_attempted
    crawl.fetch.assert_not_called()
    assert "continuation" in route.legacy_out(8000)


@pytest.mark.asyncio
async def test_complete_content_accepted():
    http = _Fake("http", {ProviderCapability.FETCH}, _resp())
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.action == RecoveryAction.ACCEPT
    assert route.recovery_outcome == "accepted"
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_complete_short_page_accepted():
    http = _Fake("http", {ProviderCapability.FETCH}, _resp(content="short page", raw_html="<html>short</html>"))
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.reason == RecoveryReason.COMPLETE_SHORT_PAGE
    assert route.recovery_outcome == "accepted"
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_plain_403_stops_no_browser():
    http = _Fake(
        "http", {ProviderCapability.FETCH}, _resp(status_code=403, content="Forbidden", raw_html="<html>nope</html>")
    )
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.reason == RecoveryReason.ACCESS_DENIED
    assert route.recovery_decision.action == RecoveryAction.STOP
    assert route.recovery_outcome == "terminal"
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_429_deferred_no_extra_fetch():
    http = _Fake(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=429, content="", error_code=StandardErrorCode.FETCH_RATE_LIMITED),
    )
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.action == RecoveryAction.RETRY_LATER
    assert route.recovery_outcome == "deferred"
    assert http.fetch.await_count == 1
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_network_failure_no_second_retry_loop():
    http = _Fake(
        "http",
        {ProviderCapability.FETCH},
        _resp(
            status_code=0,
            content="",
            error="connect failed",
            error_code=StandardErrorCode.FETCH_CONNECTION_ERROR,
            retryable=True,
        ),
    )
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.action == RecoveryAction.RETRY
    assert route.recovery_outcome == "retry_delegated_to_fetcher"
    # Service must NOT re-invoke the provider (Fetcher already retried 3x).
    assert http.fetch.await_count == 1
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_401_requires_auth_no_retry():
    http = _Fake("http", {ProviderCapability.FETCH}, _resp(status_code=401, content=""))
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.action == RecoveryAction.REQUIRE_AUTH
    assert route.recovery_outcome == "user_action_required"
    assert http.fetch.await_count == 1
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_451_stop_no_browser_no_retry():
    http = _Fake("http", {ProviderCapability.FETCH}, _resp(status_code=451, content=""))
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.action == RecoveryAction.STOP
    assert route.recovery_outcome == "terminal"
    assert http.fetch.await_count == 1
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_ambiguous_no_action_no_browser():
    http = _Fake("http", {ProviderCapability.FETCH}, _resp(content="   ", raw_html=""))
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_decision.action == RecoveryAction.NONE
    assert route.recovery_outcome == "no_action"
    crawl.fetch.assert_not_called()


# --- provider fallback ------------------------------------------------------


@pytest.mark.asyncio
async def test_tls_failure_fallback_to_alternate_once_success():
    bad = _Fake(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=0, content="", error="ssl cert error", error_code=StandardErrorCode.FETCH_SSL_ERROR),
    )
    good = _Fake("http2", {ProviderCapability.FETCH}, _resp(provider="http2", content="recovered body " * 20))
    crawl = _browser()
    svc, reg, _ = _service([bad, good, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.primary_provider == "http"
    assert route.recovery_decision.action == RecoveryAction.PROVIDER_FALLBACK
    assert good.fetch.await_count == 1
    assert route.fallback_used
    assert route.fallback_provider == "http2"
    assert route.recovery_outcome == "fallback_success"
    assert route.final_response.provider == "http2"
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_failure_keeps_primary_no_third_provider():
    bad = _Fake(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=0, content="", error="ssl cert error", error_code=StandardErrorCode.FETCH_SSL_ERROR),
    )
    alt = _Fake(
        "http2",
        {ProviderCapability.FETCH},
        _resp(
            provider="http2", status_code=0, content="", error="also ssl", error_code=StandardErrorCode.FETCH_SSL_ERROR
        ),
    )
    svc, _, _ = _service([bad, alt])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert alt.fetch.await_count == 1
    assert not route.fallback_used
    assert route.recovery_outcome == "fallback_failed"
    assert route.final_response.provider == "http"


@pytest.mark.asyncio
async def test_fallback_unavailable_keeps_primary():
    bad = _Fake(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=0, content="", error="ssl cert error", error_code=StandardErrorCode.FETCH_SSL_ERROR),
    )
    crawl = _browser()
    svc, _, _ = _service([bad, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.recovery_outcome == "fallback_unavailable"
    assert route.final_response.provider == "http"
    # Browser must never be used as a FETCH fallback.
    crawl.fetch.assert_not_called()


# --- browser outcomes & legacy contract ------------------------------------


@pytest.mark.asyncio
async def test_browser_unavailable_keeps_primary():
    html = "<html><body>Please enable JavaScript to continue.<noscript></noscript></body></html>"
    http = _Fake("http", {ProviderCapability.FETCH}, _resp(content="Please enable JavaScript.", raw_html=html))
    svc, _, _ = _service([http])  # no BROWSER provider
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.browser_attempted is False
    assert route.recovery_outcome == "browser_unavailable"
    assert route.final_response.provider == "http"
    assert route.escalation_decision is not None  # derived from recovery


@pytest.mark.asyncio
async def test_browser_failure_keeps_fast_and_legacy_fields():
    html = "<html><body>Please enable JavaScript to continue.<noscript></noscript></body></html>"
    http = _Fake("http", {ProviderCapability.FETCH}, _resp(content="Please enable JavaScript.", raw_html=html))
    crawl = _browser(content="", status=500, error="sidecar down")
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.browser_attempted
    assert not route.browser_success
    assert route.recovery_outcome == "browser_failed"
    assert route.final_response.provider == "http"
    out = route.legacy_out(8000)
    assert out["browser_attempted"] is True
    assert out["browser_success"] is False
    assert out["escalation"]["reason_code"] == "JS_REQUIRED"


@pytest.mark.asyncio
async def test_browser_success_legacy_contract_and_no_fast_continuation():
    html = "<html><body>Please enable JavaScript to continue.<noscript></noscript></body></html>"
    fast = _resp(content="Please enable JavaScript.", raw_html=html)
    http = _Fake("http", {ProviderCapability.FETCH}, fast)
    crawl = _browser(content="rendered full article " * 100)
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    assert route.browser_success
    out = route.legacy_out(8000)
    assert out["browser_success"] is True
    assert out["browser_backend"] == "crawl4ai"
    assert out["escalation"]["escalate"] is True
    # Browser final content is not windowed -> no fast-snapshot continuation.
    assert "continuation" not in out


# --- continuation fast path stays shortest ---------------------------------


@pytest.mark.asyncio
async def test_snapshot_hit_skips_recovery_browser_jev():
    snap = _resp(
        provider="http",
        content="c" * 100,
        metadata={
            "served_from_content_snapshot": True,
            "content_total_chars": 9000,
            "content_start_char": 8000,
            "content_end_char": 8100,
            "has_more": True,
            "next_start_char": 8100,
            "remaining_chars": 900,
        },
    )
    http = _Fake("http", {ProviderCapability.FETCH}, snap)
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    route = await svc.fetch(FetchRequest(url="https://example.com", start_char=8000))
    assert route.recovery_decision is None
    assert route.recovery_outcome is None
    assert not route.browser_attempted
    crawl.fetch.assert_not_called()
    assert http.fetch.await_count == 1  # served from snapshot inside provider; no extra orchestration call
    out = route.legacy_out(8000)
    assert out["continuation"]["served_from_snapshot"] is True


# --- observability: single counts ------------------------------------------


@pytest.mark.asyncio
async def test_observability_classification_and_execution_counted_once():
    html = "<html><body>Please enable JavaScript to continue.<noscript></noscript></body></html>"
    http = _Fake("http", {ProviderCapability.FETCH}, _resp(content="Please enable JavaScript.", raw_html=html))
    crawl = _browser()
    svc, _, _ = _service([http, crawl])
    await svc.fetch(FetchRequest(url="https://example.com"))
    s = get_observability_summary()
    assert s["recovery_reasons"].get("JS_REQUIRED") == 1
    assert s["recovery_actions"].get("BROWSER") == 1
    assert s["recovery_execution"]["BROWSER"].get("browser_success") == 1


@pytest.mark.asyncio
async def test_observability_continue_and_deferred():
    trunc = _resp(
        metadata={
            "truncated_by_output_limit": True,
            "content_total_chars": 9000,
            "content_start_char": 0,
            "content_end_char": 8000,
            "has_more": True,
            "next_start_char": 8000,
            "remaining_chars": 1000,
        }
    )
    http1 = _Fake("h1", {ProviderCapability.FETCH}, trunc)
    svc, _, _ = _service([http1])
    await svc.fetch(FetchRequest(url="https://example.com"))
    rl = _Fake(
        "h2",
        {ProviderCapability.FETCH},
        _resp(status_code=429, content="", error_code=StandardErrorCode.FETCH_RATE_LIMITED),
    )
    svc2, _, _ = _service([rl])
    await svc2.fetch(FetchRequest(url="https://example.com"))
    s = get_observability_summary()
    assert s["recovery_execution"]["CONTINUE_CONTENT"]["continuation_ready"] == 1
    assert s["recovery_execution"]["RETRY_LATER"]["deferred"] == 1


def test_mcp_tool_count_unchanged():
    from pathlib import Path

    server = Path(fs_mod.__file__).with_name("server.py").read_text()
    assert server.count("@mcp.tool()") == 11
