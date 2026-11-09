"""v1.4.0 Phase 2 — Deterministic Search Recovery tests."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.exceptions import SearchParseError
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter
from webscout_mcp.search_provider import (
    SearchFailureKind,
    SearchProvider,
    SearchRequest,
    SearchResponse,
    SearchStatus,
)
from webscout_mcp.search_recovery import (
    SearchRecoveryAction,
    SearchRecoveryDecision,
    SearchRecoveryReason,
    classify_circuit_open,
    classify_search_final_outcome,
    classify_search_recovery,
)
from webscout_mcp.search_service import SearchService, SearchServiceConfig
from webscout_mcp.tavily_provider import TavilySearchProvider


def _results(n, backend="t"):
    from webscout_mcp.search import SearchResult

    return [
        SearchResult(position=i, title=f"r{i}", url=f"https://e.com/{i}", snippet="", backend=backend) for i in range(n)
    ]


class _FakeProvider:
    def __init__(self, name, handler):
        self.name = name
        self.handler = handler
        self.calls = 0

    async def search(self, request):
        self.calls += 1
        result = self.handler(request)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    async def close(self):
        pass


def _svc(handlers, router=False, threshold=3, recovery=60):
    providers = [_FakeProvider(n, h) for n, h in handlers]
    cfg = SearchServiceConfig(circuit_failure_threshold=threshold, circuit_recovery_time=recovery)
    rtr = None
    if router:
        rtr = ProviderRouter(
            provider_names=[p.name for p in providers],
            cost_tiers={p.name: ProviderCostTier.FREE for p in providers},
            prefer_free=True,
            min_score_threshold=0.0,
            capabilities={p.name: {ProviderCapability.SEARCH} for p in providers},
        )
    return SearchService(providers=providers, config=cfg, router=rtr)


# --- error type integrity: Tavily -----------------------------------------


def test_tavily_string_error_types_removed():
    import inspect

    src = inspect.getsource(TavilySearchProvider.search)
    # No bare string error_type assignments remain.
    assert 'error_type="auth_error"' not in src
    assert 'error_type="rate_limited"' not in src
    assert 'error_type="timeout"' not in src
    assert 'error_type="connection_error"' not in src
    assert 'error_type="unknown_error"' not in src
    assert 'error_type="not_configured"' not in src


def test_tavily_to_dict_does_not_crash_on_auth():
    p = TavilySearchProvider(SimpleNamespace(tavily_api_key=None, tavily_timeout=1.0))
    resp = asyncio.run(p.search(SearchRequest(query="q")))
    assert resp.is_error
    assert isinstance(resp.error_type, StandardErrorCode)
    assert resp.failure_kind == SearchFailureKind.CONFIG
    # to_dict must not raise on .value
    assert resp.to_dict()["error_type"] is not None


def test_tavily_429_maps_rate_limited(monkeypatch):
    class _Resp:
        status_code = 429

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    class _Client:
        async def post(self, *a, **k):
            return _Resp()

        async def aclose(self):
            pass

    p = TavilySearchProvider(SimpleNamespace(tavily_api_key="k", tavily_timeout=1.0))
    p._client = _Client()
    resp = asyncio.run(p.search(SearchRequest(query="q")))
    assert resp.error_type == StandardErrorCode.SEARCH_RATE_LIMITED
    assert resp.failure_kind == SearchFailureKind.RATE_LIMITED


def test_tavily_timeout_maps_search_timeout(monkeypatch):
    import httpx

    class _Client:
        async def post(self, *a, **k):
            raise httpx.TimeoutException("boom")

        async def aclose(self):
            pass

    p = TavilySearchProvider(SimpleNamespace(tavily_api_key="k", tavily_timeout=1.0))
    p._client = _Client()
    resp = asyncio.run(p.search(SearchRequest(query="q")))
    assert resp.error_type == StandardErrorCode.SEARCH_TIMEOUT
    assert resp.failure_kind == SearchFailureKind.TIMEOUT


# --- adapter parser failure -----------------------------------------------


class _ParserBackend:
    name = "bing"

    async def search(self, **kw):
        raise SearchParseError("q", "bing", "no results parsed from Bing HTML")

    async def close(self):
        pass


def test_adapter_parser_failure_is_parser_kind():
    from webscout_mcp.search_provider_adapter import SearchBackendAdapter

    adapter = SearchBackendAdapter(_ParserBackend())
    resp = asyncio.run(adapter.search(SearchRequest(query="q")))
    assert resp.is_error
    assert resp.failure_kind == SearchFailureKind.PARSER
    assert resp.error_type == StandardErrorCode.CONTENT_PARSE_ERROR


# --- recovery classifier --------------------------------------------------


@pytest.mark.parametrize(
    "kind,expected_reason",
    [
        (SearchFailureKind.TIMEOUT, SearchRecoveryReason.TIMEOUT),
        (SearchFailureKind.RATE_LIMITED, SearchRecoveryReason.RATE_LIMITED),
        (SearchFailureKind.AUTH, SearchRecoveryReason.AUTH_ERROR),
        (SearchFailureKind.PARSER, SearchRecoveryReason.PARSER_FAILURE),
        (SearchFailureKind.NETWORK, SearchRecoveryReason.NETWORK_FAILURE),
        (SearchFailureKind.SERVER, SearchRecoveryReason.SERVER_ERROR),
        (SearchFailureKind.CONFIG, SearchRecoveryReason.CONFIG_ERROR),
        (SearchFailureKind.PROVIDER, SearchRecoveryReason.PROVIDER_ERROR),
        (SearchFailureKind.INVALID_REQUEST, SearchRecoveryReason.INVALID_QUERY),
    ],
)
def test_error_kind_maps_to_try_next_or_stop(kind, expected_reason):
    resp = SearchResponse.error(query="q", provider="p", error_type=StandardErrorCode.SEARCH_BACKEND_FAILED)
    resp.failure_kind = kind
    d = classify_search_recovery(resp)
    assert d.reason == expected_reason
    if kind == SearchFailureKind.INVALID_REQUEST:
        assert d.action == SearchRecoveryAction.STOP
    else:
        assert d.action == SearchRecoveryAction.TRY_NEXT_PROVIDER


def test_success_maps_accept():
    resp = SearchResponse.success("q", "p", _results(2))
    d = classify_search_recovery(resp)
    assert d.reason == SearchRecoveryReason.RESULT_AVAILABLE
    assert d.action == SearchRecoveryAction.ACCEPT


def test_empty_maps_try_next():
    resp = SearchResponse.empty("q", "p")
    d = classify_search_recovery(resp)
    assert d.reason == SearchRecoveryReason.EMPTY_RESULT
    assert d.action == SearchRecoveryAction.TRY_NEXT_PROVIDER


def test_finalizer_all_empty():
    d = classify_search_final_outcome(
        [
            classify_search_recovery(SearchResponse.empty("q", "a")),
            classify_search_recovery(SearchResponse.empty("q", "b")),
        ]
    )
    assert d.reason == SearchRecoveryReason.ALL_EMPTY
    assert d.action == SearchRecoveryAction.RETURN_EMPTY


def test_finalizer_error_plus_empty_is_all_empty():
    err = SearchResponse.error("q", "a", StandardErrorCode.SEARCH_BACKEND_FAILED)
    err.failure_kind = SearchFailureKind.NETWORK
    d = classify_search_final_outcome(
        [classify_search_recovery(err), classify_search_recovery(SearchResponse.empty("q", "b"))]
    )
    assert d.reason == SearchRecoveryReason.ALL_EMPTY
    assert d.action == SearchRecoveryAction.RETURN_EMPTY


def test_finalizer_all_error():
    err = SearchResponse.error("q", "a", StandardErrorCode.SEARCH_BACKEND_FAILED)
    err.failure_kind = SearchFailureKind.NETWORK
    d = classify_search_final_outcome([classify_search_recovery(err)])
    assert d.reason == SearchRecoveryReason.ALL_FAILED
    assert d.action == SearchRecoveryAction.RETURN_ERROR


def test_finalizer_invalid_query_wins():
    err = SearchResponse.error("q", "a", StandardErrorCode.SEARCH_INVALID_QUERY)
    err.failure_kind = SearchFailureKind.INVALID_REQUEST
    d = classify_search_final_outcome(
        [classify_search_recovery(err), classify_search_recovery(SearchResponse.empty("q", "b"))]
    )
    assert d.action == SearchRecoveryAction.STOP


# --- SearchService timeout code -------------------------------------------


def test_service_timeout_uses_search_timeout_not_fetch_timeout():
    async def slow(req):
        await asyncio.sleep(0.2)
        return SearchResponse.empty(req.query, "a")

    s = _svc([("a", slow), ("b", lambda r: _ok(r))])
    s.config.request_timeout = 0.01
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.is_success and out.provider == "b"
    trace = out.extra["route_trace"]
    a_entry = next(t for t in trace if t["provider"] == "a")
    assert a_entry["recovery_reason"] == SearchRecoveryReason.TIMEOUT.value
    # The synthetic timeout response recorded internally must be SEARCH_TIMEOUT.
    # (Not directly returned, but route_trace reason proves classification.)


def _ok(req, provider="b"):
    return SearchResponse.success(req.query, provider, _results(2, backend=provider))


# --- circuit authority (dynamic router) -----------------------------------


def test_dynamic_router_skips_open_circuit_provider():
    async def fail(req):
        return SearchResponse.error(req.query, "a", StandardErrorCode.SEARCH_BACKEND_FAILED)

    s = _svc([("a", fail), ("b", lambda r: _ok(r))], router=True, threshold=2)
    # Trip A's SearchHealthManager circuit directly (dynamic router would otherwise
    # rank B first after A's first failure).
    s.health_manager.record_failure("a", "e1")
    s.health_manager.record_failure("a", "e2")
    assert s.health_manager.get_backend("a").circuit_open is True
    # Force the router to still rank A first (router circuit is NOT the
    # authority for SEARCH) to prove SearchHealthManager gate is enforced.
    s.router.set_circuit_closed("a")
    for _ in range(5):
        s.router.record_result("a", True, 10.0)
    a_provider = s.providers[0]
    calls_before = a_provider.calls
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.provider == "b"
    assert a_provider.calls == calls_before
    trace = out.extra["route_trace"]
    a_entry = next(t for t in trace if t["provider"] == "a")
    assert a_entry["result"] == "skipped"
    assert a_entry["reason"] == "CIRCUIT_OPEN"


def test_empty_does_not_open_circuit_dynamic():
    async def empty(req):
        return SearchResponse.empty(req.query, "a")

    s = _svc([("a", empty), ("b", lambda r: _ok(r))], router=False, threshold=2)
    for i in range(10):
        asyncio.run(s.search(SearchRequest(query=f"q{i}")))
    assert s.health_manager.get_backend("a").circuit_open is False


def test_half_open_success_closes_circuit():
    async def fail_then_ok(req):
        # fail until circuit opens, then succeed
        b = s.health_manager.get_backend("a")
        if b.circuit_open:
            return SearchResponse.success(req.query, "a", _results(1))
        return SearchResponse.error(req.query, "a", StandardErrorCode.SEARCH_BACKEND_FAILED)

    s = _svc([("a", fail_then_ok), ("b", lambda r: _ok(r))], router=False, threshold=2, recovery=0)
    for i in range(2):
        asyncio.run(s.search(SearchRequest(query=f"q{i}")))
    assert s.health_manager.get_backend("a").circuit_open is True
    # recovery=0 -> can_use() allows half-open
    out = asyncio.run(s.search(SearchRequest(query="q2")))
    assert out.provider == "a"
    assert s.health_manager.get_backend("a").circuit_open is False


def test_half_open_failure_resets_timer():
    async def always_fail(req):
        return SearchResponse.error(req.query, "a", StandardErrorCode.SEARCH_BACKEND_FAILED)

    s = _svc([("a", always_fail), ("b", lambda r: _ok(r))], router=False, threshold=1, recovery=0)
    asyncio.run(s.search(SearchRequest(query="q0")))
    assert s.health_manager.get_backend("a").circuit_open is True
    t0 = s.health_manager.get_backend("a").circuit_open_time
    time.sleep(0.01)
    asyncio.run(s.search(SearchRequest(query="q1")))
    t1 = s.health_manager.get_backend("a").circuit_open_time
    assert t1 is not None and (t0 is None or t1 >= t0)


# --- production behavior regression ---------------------------------------


def test_empty_then_success_returns_b():
    s = _svc([("a", lambda r: SearchResponse.empty(r.query, "a")), ("b", lambda r: _ok(r))])
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.is_success and out.provider == "b"


def test_error_then_empty_aggregate_empty():
    err = SearchResponse.error("q", "a", StandardErrorCode.SEARCH_BACKEND_FAILED)
    s = _svc([("a", lambda r: err), ("b", lambda r: SearchResponse.empty(r.query, "b"))])
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.is_empty and out.provider == "all"
    assert s.total_errors == 0


def test_all_error_returns_all_backends_failed():
    err = SearchResponse.error("q", "a", StandardErrorCode.SEARCH_BACKEND_FAILED)
    s = _svc([("a", lambda r: err), ("b", lambda r: err)])
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.error_type == StandardErrorCode.SEARCH_ALL_BACKENDS_FAILED
