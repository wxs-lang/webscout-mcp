"""Phase 1 (v1.4.0) search semantics & result integrity tests.

Covers cache identity isolation, EMPTY vs ERROR three-state semantics,
soft misses not polluting provider health/circuit, aggregate EMPTY vs
ALL-ERROR, deterministic fallback reasons, route trace, and the
config field-name drift fix.
"""

from __future__ import annotations

import asyncio

import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.search_provider import SearchRequest, SearchResponse, SearchStatus
from webscout_mcp.search_service import FallbackReason, SearchService, SearchServiceConfig


class _FakeProvider:
    """Minimal stub implementing enough of SearchProvider for the service."""

    def __init__(self, name: str, handler):
        self.name = name
        self.handler = handler  # async fn(request) -> SearchResponse
        self.calls = 0

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.calls += 1
        return await self.handler(request)

    async def close(self) -> None:
        pass


def _ok(req, provider):
    return SearchResponse.success(req.query, provider, results=[])  # -> EMPTY via post_init


def _results(n):
    from webscout_mcp.search import SearchResult

    return [
        SearchResult(position=i, title=f"r{i}", url=f"https://e.com/{i}", snippet="", backend="t") for i in range(n)
    ]


def svc(handlers, **kw):
    providers = [_FakeProvider(name, h) for name, h in handlers]
    return SearchService(providers=providers, config=SearchServiceConfig(), **kw)


# --- cache identity -------------------------------------------------------


def test_cache_key_isolates_safe_search():
    s = svc([("a", lambda r: None)])
    r1 = SearchRequest(query="python", safe_search=False)
    r2 = SearchRequest(query="python", safe_search=True)
    assert s._get_cache_key(r1) != s._get_cache_key(r2)


def test_cache_key_isolates_country():
    s = svc([("a", lambda r: None)])
    assert s._get_cache_key(SearchRequest(query="q", country="us")) != s._get_cache_key(
        SearchRequest(query="q", country="cn")
    )


def test_cache_key_isolates_region_language_maxresults():
    s = svc([("a", lambda r: None)])
    base = SearchRequest(query="q")
    for field, val in (("region", "us-en"), ("language", "zh"), ("max_results", 5)):
        a = s._get_cache_key(base)
        b = s._get_cache_key(SearchRequest(query="q", **{field: val}))
        assert a != b, field


def test_cache_key_normalizes_whitespace_and_case():
    s = svc([("a", lambda r: None)])
    a = s._get_cache_key(SearchRequest(query=" python "))
    b = s._get_cache_key(SearchRequest(query="PYTHON"))
    assert a == b


def test_semantic_same_request_hits_cache():
    async def handler(req):
        return SearchResponse.success(req.query, "a", results=_results(3))

    s = svc([("a", handler)])
    asyncio.run(s.search(SearchRequest(query="python")))
    asyncio.run(s.search(SearchRequest(query="python")))
    assert s.cache_hits == 1 and s.cache_misses == 1


# --- EMPTY vs ERROR three-state ------------------------------------------


def test_empty_falls_through_to_success_not_failure():
    async def a(req):
        return SearchResponse.empty(req.query, "a")

    async def b(req):
        return SearchResponse.success(req.query, "b", results=_results(2))

    s = svc([("a", a), ("b", b)])
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.is_success and out.provider == "b"
    # A must NOT be recorded as a hard failure.
    assert s.provider_outcomes["a"]["empty"] == 1
    assert s.provider_outcomes["a"]["error"] == 0
    assert s.total_errors == 0
    assert s.fallback_reasons.get(FallbackReason.EMPTY_RESULT) == 1
    # fallback counted because >1 provider attempted
    assert s.total_fallbacks == 1


def test_empty_does_not_open_circuit():
    async def a(req):
        return SearchResponse.empty(req.query, "a")

    async def b(req):
        return SearchResponse.success(req.query, "b", results=_results(1))

    s = svc([("a", a), ("b", b)])
    for _ in range(10):
        asyncio.run(s.search(SearchRequest(query="q")))
    backend = s.health_manager.get_backend("a")
    assert not backend.circuit_open
    assert backend.consecutive_failures == 0


def test_all_empty_returns_aggregate_empty_not_error():
    async def empty(req):
        return SearchResponse.empty(req.query, "x")

    s = svc([("x", empty), ("y", empty)])
    out = asyncio.run(s.search(SearchRequest(query="zzz-nope")))
    assert out.is_empty and out.provider == "all"
    assert out.error_type is None
    assert s.total_errors == 0
    # count=0 externally
    assert len(out.results) == 0


def test_all_error_returns_all_backends_failed():
    async def err(req):
        return SearchResponse.error(req.query, "x", StandardErrorCode.SEARCH_BACKEND_FAILED, "boom")

    s = svc([("x", err), ("y", err)])
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.is_error
    assert out.error_type == StandardErrorCode.SEARCH_ALL_BACKENDS_FAILED
    assert s.total_errors == 1


def test_error_then_empty_mixes_to_aggregate_empty():
    async def err(req):
        return SearchResponse.error(req.query, "x", StandardErrorCode.SEARCH_BACKEND_FAILED, "boom")

    async def empty(req):
        return SearchResponse.empty(req.query, "y")

    s = svc([("x", err), ("y", empty)])
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.is_empty and out.provider == "all"
    # mixed: at least one hard error, but a completed empty => no system error
    assert s.total_errors == 0
    trace = {t["provider"]: t["result"] for t in out.extra["route_trace"]}
    assert trace["x"] == "error" and trace["y"] == "empty"


def test_parse_failure_is_error_not_empty():
    # provider raises -> service catches -> ERROR (parser drift must not look empty)
    async def boom(req):
        raise RuntimeError("selector extracted 0")

    async def ok(req):
        return SearchResponse.success(req.query, "b", results=_results(1))

    s = svc([("a", boom), ("b", ok)])
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.is_success and out.provider == "b"
    assert s.provider_outcomes["a"]["error"] == 1
    assert s.fallback_reasons.get(FallbackReason.PROVIDER_ERROR) == 1


def test_timeout_reason_and_no_hard_success():
    async def slow(req):
        await asyncio.sleep(0.2)
        return SearchResponse.empty(req.query, "a")

    async def ok(req):
        return SearchResponse.success(req.query, "b", results=_results(1))

    s = svc(
        [("a", slow), ("b", ok)],
    )
    s.config.request_timeout = 0.01
    out = asyncio.run(s.search(SearchRequest(query="q")))
    assert out.is_success and out.provider == "b"
    assert s.fallback_reasons.get(FallbackReason.TIMEOUT) == 1


# --- cache only stores success -------------------------------------------


def test_empty_and_error_never_cached():
    async def empty(req):
        return SearchResponse.empty(req.query, "a")

    s = svc([("a", empty)])
    asyncio.run(s.search(SearchRequest(query="q")))
    assert len(s._search_cache) == 0


# --- route trace ----------------------------------------------------------


def test_route_trace_recorded_on_success():
    async def empty(req):
        return SearchResponse.empty(req.query, "a")

    async def ok(req):
        return SearchResponse.success(req.query, "b", results=_results(2))

    s = svc([("a", empty), ("b", ok)])
    out = asyncio.run(s.search(SearchRequest(query="q")))
    trace = out.extra["route_trace"]
    assert [t["provider"] for t in trace] == ["a", "b"]
    assert trace[0]["result"] == "empty" and trace[1]["result"] == "success"


# --- config field drift ---------------------------------------------------


def test_factory_reads_correct_config_fields():
    from types import SimpleNamespace

    from webscout_mcp.search_service import create_search_service_from_config

    cfg = SimpleNamespace(
        search_circuit_failure_threshold=9,
        search_circuit_recovery_time=123,
        request_timeout=25.0,
        search_safe_search=False,
    )
    svc_inst = create_search_service_from_config(cfg)
    try:
        assert svc_inst.config.circuit_failure_threshold == 9
        assert svc_inst.config.circuit_recovery_time == 123
        assert svc_inst.config.request_timeout == 25.0
    finally:
        asyncio.run(svc_inst.close())


def test_safe_search_default_not_drift_mid_layer():
    # SearchRequest default safe_search=False; server layer supplies True.
    req = SearchRequest(query="q")
    assert req.safe_search is False
    # Explicit True must survive into the normalized request used downstream.
    req2 = SearchRequest(query="q", safe_search=True)
    assert req2.safe_search is True
