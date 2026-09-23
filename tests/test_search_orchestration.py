"""v1.4.0 Phase 3 — Unified Search Recovery Orchestration tests.

Verifies that SearchService production behavior is driven by
SearchRecoveryDecision (not parallel if/else), that each provider is called
at most once per request, that STOP halts the chain, and that server.web_search
no longer falls back to legacy SearchEngine per-request.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from webscout_mcp.errors import StandardErrorCode
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
    SearchRecoveryReason,
)
from webscout_mcp.search_service import SearchService, SearchServiceConfig

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _results(n, backend="t"):
    from webscout_mcp.search import SearchResult

    return [
        SearchResult(position=i, title=f"r{i}", url=f"https://e.com/{i}", snippet="", backend=backend) for i in range(n)
    ]


def _ok(n=3, provider="t"):
    return SearchResponse(
        status=SearchStatus.SUCCESS,
        query="q",
        provider=provider,
        results=_results(n, provider),
    )


def _empty(provider="t"):
    return SearchResponse(status=SearchStatus.EMPTY, query="q", provider=provider, results=[])


def _err(reason=SearchRecoveryReason.TIMEOUT, provider="t"):
    kind_map = {
        SearchRecoveryReason.TIMEOUT: SearchFailureKind.TIMEOUT,
        SearchRecoveryReason.RATE_LIMITED: SearchFailureKind.RATE_LIMITED,
        SearchRecoveryReason.AUTH_ERROR: SearchFailureKind.AUTH,
        SearchRecoveryReason.PARSER_FAILURE: SearchFailureKind.PARSER,
        SearchRecoveryReason.NETWORK_FAILURE: SearchFailureKind.NETWORK,
        SearchRecoveryReason.SERVER_ERROR: SearchFailureKind.SERVER,
        SearchRecoveryReason.CONFIG_ERROR: SearchFailureKind.CONFIG,
        SearchRecoveryReason.PROVIDER_ERROR: SearchFailureKind.PROVIDER,
        SearchRecoveryReason.INVALID_QUERY: SearchFailureKind.INVALID_REQUEST,
    }
    code_map = {
        SearchRecoveryReason.TIMEOUT: StandardErrorCode.SEARCH_TIMEOUT,
        SearchRecoveryReason.RATE_LIMITED: StandardErrorCode.SEARCH_RATE_LIMITED,
        SearchRecoveryReason.AUTH_ERROR: StandardErrorCode.FETCH_FORBIDDEN,
        SearchRecoveryReason.PARSER_FAILURE: StandardErrorCode.CONTENT_PARSE_ERROR,
        SearchRecoveryReason.NETWORK_FAILURE: StandardErrorCode.FETCH_CONNECTION_ERROR,
        SearchRecoveryReason.SERVER_ERROR: StandardErrorCode.FETCH_SERVER_ERROR,
        SearchRecoveryReason.CONFIG_ERROR: StandardErrorCode.SYSTEM_CONFIG_ERROR,
        SearchRecoveryReason.PROVIDER_ERROR: StandardErrorCode.SEARCH_BACKEND_FAILED,
        SearchRecoveryReason.INVALID_QUERY: StandardErrorCode.SEARCH_INVALID_QUERY,
    }
    return SearchResponse.error(
        query="q",
        provider=provider,
        error_type=code_map[reason],
        error_message=reason.value,
        retryable=True,
        failure_kind=kind_map[reason],
    )


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


def _req(q="python"):
    return SearchRequest(query=q, max_results=5)


# ---------------------------------------------------------------------------
# 1-10: per-reason action dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_returns_immediately():
    svc = _svc([("a", lambda r: _ok(provider="a")), ("b", lambda r: _ok(provider="b"))])
    resp = await svc.search(_req())
    assert resp.is_success
    assert resp.provider == "a"
    assert svc.providers[1].calls == 0


@pytest.mark.asyncio
async def test_empty_try_next():
    svc = _svc([("a", lambda r: _empty(provider="a")), ("b", lambda r: _ok(provider="b"))])
    resp = await svc.search(_req())
    assert resp.is_success
    assert resp.provider == "b"
    assert svc.providers[0].calls == 1
    assert svc.providers[1].calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        SearchRecoveryReason.TIMEOUT,
        SearchRecoveryReason.RATE_LIMITED,
        SearchRecoveryReason.AUTH_ERROR,
        SearchRecoveryReason.PARSER_FAILURE,
        SearchRecoveryReason.NETWORK_FAILURE,
        SearchRecoveryReason.SERVER_ERROR,
        SearchRecoveryReason.CONFIG_ERROR,
        SearchRecoveryReason.PROVIDER_ERROR,
    ],
)
async def test_hard_error_try_next(reason):
    svc = _svc([("a", lambda r: _err(reason)), ("b", lambda r: _ok(provider="b"))])
    resp = await svc.search(_req("q_" + reason.value))
    assert resp.is_success
    assert resp.provider == "b"
    trace = resp.extra.get("route_trace", [])
    assert trace[0]["recovery_reason"] == reason.value
    assert trace[0]["recommended_action"] == SearchRecoveryAction.TRY_NEXT_PROVIDER.value


# ---------------------------------------------------------------------------
# 11: STOP immediately
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_query_stops_immediately():
    svc = _svc(
        [
            ("a", lambda r: _err(SearchRecoveryReason.INVALID_QUERY, provider="a")),
            ("b", lambda r: _ok(provider="b")),
            ("c", lambda r: _ok(provider="c")),
        ]
    )
    resp = await svc.search(_req())
    assert not resp.is_success
    assert resp.error_type == StandardErrorCode.SEARCH_INVALID_QUERY
    assert svc.providers[0].calls == 1
    assert svc.providers[1].calls == 0
    assert svc.providers[2].calls == 0
    # INVALID_QUERY must not pollute provider circuit.
    backend = svc.health_manager.get_backend("a")
    assert backend.consecutive_failures == 0
    assert not backend.circuit_open


# ---------------------------------------------------------------------------
# 12: circuit open -> skip, 0 network
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_circuit_open_skip_no_network():
    svc = _svc([("a", lambda r: _ok(provider="a")), ("b", lambda r: _ok(provider="b"))], threshold=2)
    # trip A's circuit
    svc.health_manager.record_failure("a", "x")
    svc.health_manager.record_failure("a", "x")
    assert svc.health_manager.get_backend("a").circuit_open
    resp = await svc.search(_req())
    assert resp.provider == "b"
    assert svc.providers[0].calls == 0
    trace = resp.extra["route_trace"]
    assert trace[0]["result"] == "skipped"
    assert trace[0]["recovery_reason"] == SearchRecoveryReason.CIRCUIT_OPEN.value
    assert trace[0]["execution_outcome"] == "circuit_skipped"


# ---------------------------------------------------------------------------
# 13: unavailable stale router entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unavailable_router_entry_continue():
    svc = _svc([("a", lambda r: _ok(provider="a"))], router=True)
    # Inject a ghost (stale router entry) that ranks above "a" but is not
    # in the SearchService provider_map.
    from webscout_mcp.provider_router import ProviderMetrics

    svc.router.metrics["ghost"] = ProviderMetrics(name="ghost")
    for _ in range(50):
        svc.router.metrics["ghost"].record_request(True, 1.0, None)
    svc.router.capabilities["ghost"] = {ProviderCapability.SEARCH}
    svc.router.cost_tiers["ghost"] = ProviderCostTier.FREE
    # Make "a" rank below ghost so ghost is tried first.
    svc.router.metrics["a"].record_request(False, 1000.0, "timeout")
    resp = await svc.search(_req())
    assert resp.is_success
    assert resp.provider == "a"
    trace = resp.extra["route_trace"]
    assert trace[0]["recovery_reason"] == SearchRecoveryReason.UNAVAILABLE.value
    assert trace[0]["execution_outcome"] == "unavailable_skipped"


# ---------------------------------------------------------------------------
# 14: NONE -> no_action_continue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_continues():
    # UNKNOWN maps to NONE; construct via a response with failure_kind=None
    # and an unmapped error_type. classify_search_recovery falls to PROVIDER_ERROR
    # normally, so force via monkeypatch.
    from webscout_mcp import search_service as ss_mod

    real = ss_mod.classify_search_recovery

    def fake(response):
        from webscout_mcp.search_recovery import SearchRecoveryDecision

        if getattr(response, "provider", None) == "a":
            return SearchRecoveryDecision(
                reason=SearchRecoveryReason.UNKNOWN,
                action=SearchRecoveryAction.NONE,
            )
        return real(response)

    with patch.object(ss_mod, "classify_search_recovery", fake):
        svc = _svc([("a", lambda r: _err(provider="a")), ("b", lambda r: _ok(provider="b"))])
        resp = await svc.search(_req("q_none"))
    assert resp.is_success
    assert resp.provider == "b"
    assert svc.recovery_execution.get("NONE", {}).get("no_action_continue", 0) >= 1


# ---------------------------------------------------------------------------
# 15-17: finalizer outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_empty_return_empty():
    svc = _svc([("a", lambda r: _empty(provider="a")), ("b", lambda r: _empty(provider="b"))])
    resp = await svc.search(_req())
    assert resp.is_empty
    assert resp.provider == "all"
    assert svc.total_errors == 0


@pytest.mark.asyncio
async def test_mixed_error_empty_return_empty():
    svc = _svc([("a", lambda r: _err(provider="a")), ("b", lambda r: _empty(provider="b"))])
    resp = await svc.search(_req("q_mix"))
    assert resp.is_empty
    assert svc.total_errors == 0


@pytest.mark.asyncio
async def test_all_error_return_error():
    svc = _svc(
        [("a", lambda r: _err(provider="a")), ("b", lambda r: _err(SearchRecoveryReason.PARSER_FAILURE, provider="b"))]
    )
    resp = await svc.search(_req("q_allerr"))
    assert not resp.is_success
    assert not resp.is_empty
    assert resp.error_type == StandardErrorCode.SEARCH_ALL_BACKENDS_FAILED
    assert svc.total_errors == 1


# ---------------------------------------------------------------------------
# 18-19: each provider max once, no same-provider retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_each_provider_max_once():
    svc = _svc(
        [
            ("a", lambda r: _err(provider="a")),
            ("b", lambda r: _err(SearchRecoveryReason.PARSER_FAILURE, provider="b")),
            ("c", lambda r: _ok(provider="c")),
        ]
    )
    await svc.search(_req("q_once"))
    assert [p.calls for p in svc.providers] == [1, 1, 1]


@pytest.mark.asyncio
async def test_no_same_provider_retry():
    counter = {"n": 0}

    def handler(r):
        counter["n"] += 1
        return _err()

    svc = _svc([("a", handler), ("b", lambda r: _ok(provider="b"))])
    await svc.search(_req("q_noretry"))
    assert counter["n"] == 1


# ---------------------------------------------------------------------------
# 20: Jev only after ACCEPT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jev_only_after_accept():
    svc = _svc([("a", lambda r: _err(provider="a")), ("b", lambda r: _ok(provider="b"))])
    fired = []
    svc._fire_jev_shadow = lambda req, resp: fired.append(resp.provider)
    await svc.search(_req("q_jev"))
    assert fired == ["b"]


# ---------------------------------------------------------------------------
# 21: cache hit bypasses orchestration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_bypasses_orchestration():
    svc = _svc([("a", lambda r: _ok(provider="a"))])
    await svc.search(_req("cacheme"))
    svc.providers[0].calls = 0
    resp = await svc.search(_req("cacheme"))
    assert resp.is_success
    assert svc.providers[0].calls == 0
    assert svc.cache_hits >= 1


# ---------------------------------------------------------------------------
# 22: fallback counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fallback_counter_on_second_provider_success():
    svc = _svc([("a", lambda r: _empty(provider="a")), ("b", lambda r: _ok(provider="b"))])
    await svc.search(_req("q_fb"))
    assert svc.total_fallbacks == 1


@pytest.mark.asyncio
async def test_no_fallback_counter_on_first_success():
    svc = _svc([("a", lambda r: _ok(provider="a"))])
    await svc.search(_req("q_nofb"))
    assert svc.total_fallbacks == 0


# ---------------------------------------------------------------------------
# 23: recovery_execution counters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_execution_counters():
    svc = _svc([("a", lambda r: _err(provider="a")), ("b", lambda r: _ok(provider="b"))])
    await svc.search(_req("q_exec"))
    ex = svc.recovery_execution
    assert ex.get("TRY_NEXT_PROVIDER", {}).get("next_provider", 0) >= 1
    assert ex.get("ACCEPT", {}).get("accepted", 0) >= 1


# ---------------------------------------------------------------------------
# 24: router metric labels
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_error_labels():
    svc = _svc(
        [
            ("a", lambda r: _err(SearchRecoveryReason.RATE_LIMITED, provider="a")),
            ("b", lambda r: _err(SearchRecoveryReason.AUTH_ERROR, provider="b")),
            ("c", lambda r: _err(SearchRecoveryReason.TIMEOUT, provider="c")),
            ("d", lambda r: _err(SearchRecoveryReason.NETWORK_FAILURE, provider="d")),
            ("e", lambda r: _err(SearchRecoveryReason.PARSER_FAILURE, provider="e")),
        ],
        router=True,
    )
    await svc.search(_req("q_labels"))
    m = svc.router.metrics
    assert m["a"].error_429 >= 1
    assert m["b"].error_403 >= 1
    assert m["c"].error_timeout >= 1
    assert m["d"].error_connection >= 1
    assert m["e"].error_other >= 1


@pytest.mark.asyncio
async def test_empty_does_not_record_router_metric():
    svc = _svc([("a", lambda r: _empty(provider="a")), ("b", lambda r: _ok(provider="b"))], router=True)
    await svc.search(_req("q_empty_router"))
    m = svc.router.metrics["a"]
    assert len(m.successes) == 0
    assert (
        getattr(m, "error_429", 0)
        + getattr(m, "error_403", 0)
        + getattr(m, "error_timeout", 0)
        + getattr(m, "error_connection", 0)
        + getattr(m, "error_other", 0)
    ) == 0


# ---------------------------------------------------------------------------
# 25: route_trace matches actual actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_trace_matches_actions():
    svc = _svc(
        [("a", lambda r: _err(provider="a")), ("b", lambda r: _empty(provider="b")), ("c", lambda r: _ok(provider="c"))]
    )
    resp = await svc.search(_req("q_trace"))
    trace = resp.extra["route_trace"]
    assert len(trace) == 3
    assert trace[0]["recovery_reason"] == SearchRecoveryReason.TIMEOUT.value
    assert trace[0]["execution_outcome"] == "next_provider"
    assert trace[1]["recovery_reason"] == SearchRecoveryReason.EMPTY_RESULT.value
    assert trace[2]["execution_outcome"] == "accepted"


# ---------------------------------------------------------------------------
# recovery_agreement is no longer unconditionally incremented
# ---------------------------------------------------------------------------


def test_no_unconditional_agreement_in_source():
    import inspect

    from webscout_mcp import search_service

    src = inspect.getsource(search_service)
    # The deprecated field is initialized but never incremented in production.
    assert 'recovery_agreement["agree"] += 1' not in src


# ---------------------------------------------------------------------------
# server.py cutover tests
# ---------------------------------------------------------------------------


class _FakeSearchService:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = 0

    async def search(self, request):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.response

    def get_health_report(self):
        return {"ok": True}


class _FakeLegacyEngine:
    def __init__(self):
        self.calls = 0

    async def search(self, *args, **kw):
        self.calls += 1
        return _results(2)

    def get_health_report(self):
        return {"legacy": True}



def _tool_text(out):
    """Extract text from call_tool result across mcp SDK versions."""
    # tuple/list form: (content_blocks, meta)
    if isinstance(out, (tuple, list)):
        blocks = out[0]
        return blocks[0].text
    # CallToolResult object
    content = getattr(out, "content", None)
    if content:
        return content[0].text
    output = getattr(out, "output", None)
    if output:
        return output
    return str(out)


def _make_server(search_svc, legacy):
    """Build an MCPServer with injected search_service / legacy engine."""
    with (
        patch("webscout_mcp.server.create_search_service_from_config", return_value=search_svc),
        patch("webscout_mcp.server.SearchEngine", return_value=legacy),
    ):
        from webscout_mcp.config import Config
        from webscout_mcp.server import create_server

        return create_server(Config())


@pytest.mark.asyncio
async def test_server_success_no_legacy_call():
    svc = _FakeSearchService(response=_ok(3))
    legacy = _FakeLegacyEngine()
    server = _make_server(svc, legacy)
    out = await server.call_tool("web_search", {"query": "hello"})
    data = json.loads(_tool_text(out))
    assert data["status"] == "success"
    assert data["count"] == 3
    assert svc.calls == 1
    assert legacy.calls == 0


@pytest.mark.asyncio
async def test_server_empty_no_legacy_call():
    svc = _FakeSearchService(response=_empty())
    legacy = _FakeLegacyEngine()
    server = _make_server(svc, legacy)
    out = await server.call_tool("web_search", {"query": "zzz"})
    data = json.loads(_tool_text(out))
    assert data["status"] == "empty"
    assert data["count"] == 0
    assert legacy.calls == 0


@pytest.mark.asyncio
async def test_server_error_no_legacy_call():
    svc = _FakeSearchService(response=_err())
    legacy = _FakeLegacyEngine()
    server = _make_server(svc, legacy)
    out = await server.call_tool("web_search", {"query": "x"})
    data = json.loads(_tool_text(out))
    assert data["status"] == "error"
    assert "error" in data
    assert data["count"] == 0
    assert legacy.calls == 0


@pytest.mark.asyncio
async def test_server_stop_no_legacy_call():
    svc = _FakeSearchService(response=_err(SearchRecoveryReason.INVALID_QUERY))
    legacy = _FakeLegacyEngine()
    server = _make_server(svc, legacy)
    out = await server.call_tool("web_search", {"query": "!!"})
    data = json.loads(_tool_text(out))
    assert data["status"] == "error"
    assert legacy.calls == 0


@pytest.mark.asyncio
async def test_server_unexpected_exception_safe_error_no_legacy():
    svc = _FakeSearchService(exc=RuntimeError("boom"))
    legacy = _FakeLegacyEngine()
    server = _make_server(svc, legacy)
    out = await server.call_tool("web_search", {"query": "x"})
    data = json.loads(_tool_text(out))
    assert data["status"] == "error"
    assert data["error"]["code"] == "SYSTEM_ERROR"
    assert "boom" not in data["error"]["message"]
    assert legacy.calls == 0


@pytest.mark.asyncio
async def test_server_none_search_service_uses_legacy():
    legacy = _FakeLegacyEngine()
    with (
        patch("webscout_mcp.server.create_search_service_from_config", side_effect=RuntimeError("init fail")),
        patch("webscout_mcp.server.SearchEngine", return_value=legacy),
    ):
        from webscout_mcp.config import Config
        from webscout_mcp.server import create_server

        server = create_server(Config())
    out = await server.call_tool("web_search", {"query": "hi"})
    data = json.loads(_tool_text(out))
    assert data["count"] == 2
    assert legacy.calls == 1


@pytest.mark.asyncio
async def test_server_old_output_keys_present():
    svc = _FakeSearchService(response=_ok(2))
    legacy = _FakeLegacyEngine()
    server = _make_server(svc, legacy)
    out = await server.call_tool("web_search", {"query": "hi"})
    data = json.loads(_tool_text(out))
    assert "query" in data
    assert "count" in data
    assert "results" in data
