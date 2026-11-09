"""Tests for FetchService (Phase 2)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.fetch_provider import FetchRequest, FetchResponse
from webscout_mcp.fetch_service import FetchService
from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter


class _FakeProvider:
    name: str = "fake"
    capabilities: set[ProviderCapability] = set()

    def __init__(
        self,
        name: str,
        capabilities: set[ProviderCapability],
        response: FetchResponse | None = None,
        error: Exception | None = None,
    ):
        self.name = name
        self.capabilities = capabilities
        self._response = response
        self._error = error
        self.fetch = AsyncMock(return_value=response) if response is not None else AsyncMock(side_effect=error)
        self.close = AsyncMock()

    def get_health(self):
        return {"status": "ok"}


def _make_registry(providers: list[_FakeProvider]) -> tuple[ProviderRegistry, ProviderRouter]:
    router = ProviderRouter(
        provider_names=[p.name for p in providers],
        cost_tiers={p.name: ProviderCostTier.FREE for p in providers},
        capabilities={p.name: set(p.capabilities) for p in providers},
    )
    reg = ProviderRegistry(router=router)
    for p in providers:
        reg.register(p, capabilities=p.capabilities)
    return reg, router


def _ok_http_response(content: str = "<html><body><p>hi</p></body></html>") -> FetchResponse:
    return FetchResponse(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=200,
        provider="http",
        title="Example",
        content=content,
        content_type="text/html",
        extracted=True,
    )


def _403_response() -> FetchResponse:
    return FetchResponse(
        url="https://example.com/blocked",
        final_url="https://example.com/blocked",
        status_code=403,
        provider="http",
        content="",
        content_type="text/html",
    )


def _403_challenge_response() -> FetchResponse:
    """403 carrying a visible challenge/captcha -> SOFT_BLOCK -> BROWSER."""
    return FetchResponse(
        url="https://example.com/blocked",
        final_url="https://example.com/blocked",
        status_code=403,
        provider="http",
        content="",
        content_type="text/html",
        raw_html="<html><body>Please complete the captcha to continue (cloudflare).</body></html>",
    )


@pytest.mark.asyncio
async def test_fast_fetch_uses_fetch_capability_only():
    """Search/browser providers must not be selected for fast fetch."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _ok_http_response())
    bing = _FakeProvider("bing", {ProviderCapability.SEARCH})
    crawl = _FakeProvider("crawl4ai", {ProviderCapability.BROWSER})
    reg, _ = _make_registry([http, bing, crawl])

    svc = FetchService(registry=reg)
    req = FetchRequest(url="https://example.com/a")
    route = await svc.fetch(req)

    assert route.primary_provider == "http"
    assert not route.browser_attempted  # fast content is fine, no escalation
    assert route.route_trace[0]["provider"] == "http"


@pytest.mark.asyncio
async def test_escalation_false_does_not_call_browser():
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _ok_http_response("hi"))
    crawl = _FakeProvider("crawl4ai", {ProviderCapability.BROWSER})
    reg, _ = _make_registry([http, crawl])

    svc = FetchService(registry=reg)
    route = await svc.fetch(FetchRequest(url="https://example.com/a"))

    assert not route.browser_attempted
    crawl.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_escalation_true_calls_browser_provider():
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _403_challenge_response())
    browser_content = "<html><body>real content after render</body></html>"
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        FetchResponse(
            url="https://example.com/blocked",
            final_url="https://example.com/blocked",
            status_code=200,
            provider="crawl4ai",
            content=browser_content,
        ),
    )
    reg, _ = _make_registry([http, crawl])

    svc = FetchService(registry=reg)
    route = await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    assert route.browser_attempted
    assert route.browser_success
    assert route.final_response.provider == "crawl4ai"
    assert browser_content in route.final_response.content
    # route trace has escalation entry
    assert any(e.get("action") == "escalate" for e in route.route_trace)


@pytest.mark.asyncio
async def test_browser_failure_preserves_fast_response():
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _403_challenge_response())
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        FetchResponse(
            url="https://example.com/blocked",
            final_url="https://example.com/blocked",
            status_code=500,
            provider="crawl4ai",
            error="sidecar down",
        ),
    )
    reg, _ = _make_registry([http, crawl])

    svc = FetchService(registry=reg)
    route = await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    assert route.browser_attempted
    assert not route.browser_success
    # Fast response is preserved as final (we don't lose data when browser fails).
    assert route.final_response.provider == "http"
    assert route.final_response.status_code == 403


@pytest.mark.asyncio
async def test_route_trace_has_no_urls_or_credentials():
    """route_trace must not carry full URLs or sensitive material."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _403_response())
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        FetchResponse(
            url="https://user:pass@example.com/blocked",
            final_url="https://user:pass@example.com/blocked",
            status_code=200,
            provider="crawl4ai",
            content="rendered",
        ),
    )
    reg, _ = _make_registry([http, crawl])

    svc = FetchService(registry=reg)
    route = await svc.fetch(FetchRequest(url="https://user:pass@example.com/blocked"))

    for entry in route.route_trace:
        s = str(entry)
        assert "user:pass" not in s
        assert "example.com/blocked" not in s
        assert "password" not in s.lower()


@pytest.mark.asyncio
async def test_router_recorded_once_per_provider():
    """One fast call + one browser call => router sees exactly two records."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _403_challenge_response())
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        FetchResponse(
            url="https://example.com/blocked",
            final_url="https://example.com/blocked",
            status_code=200,
            provider="crawl4ai",
            content="rendered",
        ),
    )
    reg, router = _make_registry([http, crawl])

    svc = FetchService(registry=reg)
    await svc.fetch(FetchRequest(url="https://example.com/blocked"))

    assert router.metrics["http"].total_requests == 1
    assert router.metrics["crawl4ai"].total_requests == 1


@pytest.mark.asyncio
async def test_search_provider_never_selected_for_fetch():
    """Even if search providers are in the same registry, FETCH capability filters them out."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _ok_http_response())
    bing = _FakeProvider("bing", {ProviderCapability.SEARCH})
    reg, _ = _make_registry([http, bing])

    svc = FetchService(registry=reg)
    route = await svc.fetch(FetchRequest(url="https://example.com/a"))

    assert route.primary_provider == "http"
    bing.fetch.assert_not_called()


@pytest.mark.asyncio
async def test_web_result_in_internal_chain():
    """FetchService must produce a WebResult (Phase 1 normalization wired in)."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _ok_http_response("hello world"))
    reg, _ = _make_registry([http])

    svc = FetchService(registry=reg)
    route = await svc.fetch(FetchRequest(url="https://example.com/a"))

    assert route.web_result is not None
    assert route.web_result.content == "hello world"
    assert route.web_result.backend == "fast-http"


@pytest.mark.asyncio
async def test_legacy_out_shape_compatible():
    """legacy_out must produce the same keys web_fetch returned in v1.2.x."""
    http = _FakeProvider("http", {ProviderCapability.FETCH}, _ok_http_response("content"))
    reg, _ = _make_registry([http])

    svc = FetchService(registry=reg)
    route = await svc.fetch(FetchRequest(url="https://example.com/a"))
    out = route.legacy_out(max_chars=8000)

    for k in ("url", "status_code", "title", "content", "content_type", "extracted", "cached", "latency_ms"):
        assert k in out, f"missing key {k}"
