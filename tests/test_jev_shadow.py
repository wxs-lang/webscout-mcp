"""Tests for Jev Shadow Evaluator (Phase 2.5)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from webscout_mcp import jev_shadow, jev_store
from webscout_mcp.fetch_escalation import should_escalate_to_browser
from webscout_mcp.fetch_provider import FetchRequest, FetchResponse
from webscout_mcp.fetch_service import FetchService
from webscout_mcp.jev_client import FakeJevClient, NoopJevClient, make_jev_client
from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter
from webscout_mcp.search_provider import SearchResult


class _FakeProvider:
    name = "fake"
    capabilities = set()

    def __init__(self, name, capabilities, response=None, exc=None):
        self.name = name
        self.capabilities = capabilities
        self.fetch = AsyncMock(return_value=response) if response else AsyncMock(side_effect=exc)
        self.close = AsyncMock()

    def get_health(self):
        return {"status": "ok"}


def _reg(providers):
    router = ProviderRouter(
        provider_names=[p.name for p in providers],
        cost_tiers={p.name: ProviderCostTier.FREE for p in providers},
        capabilities={p.name: set(p.capabilities) for p in providers},
    )
    reg = ProviderRegistry(router=router)
    for p in providers:
        reg.register(p, capabilities=p.capabilities)
    return reg


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "jev_shadow.db"
    jev_store._db_path = db
    jev_store.configure(db)
    yield db
    jev_shadow.reset_for_tests()


def test_noop_when_disabled():
    cfg = SimpleNamespace(jev_enabled=False)
    client = make_jev_client(cfg)
    assert isinstance(client, NoopJevClient)


def test_fake_only_when_provider_explicit():
    # JEV_PROVIDER=fake is required; no silent fake fallback.
    cfg = SimpleNamespace(
        jev_enabled=True,
        jev_shadow_mode=True,
        jev_provider="fake",
        jev_base_url="",
        jev_api_key="",
        jev_timeout_ms=1000,
    )
    client = make_jev_client(cfg)
    assert isinstance(client, FakeJevClient)

    # Default provider=typesafe + no key -> Noop, never Fake.
    cfg2 = SimpleNamespace(
        jev_enabled=True,
        jev_shadow_mode=True,
        jev_provider="typesafe",
        jev_base_url="",
        jev_api_key="",
        jev_timeout_ms=1000,
    )
    client2 = make_jev_client(cfg2)
    assert isinstance(client2, NoopJevClient)


@pytest.mark.asyncio
async def test_jev_timeout_does_not_break_fetch(tmp_db):
    """Jev hanging must not delay the main response."""

    class HangingJev:
        name = "hanging"

        async def ask(self, q, state):
            await asyncio.sleep(5.0)  # would block if awaited
            raise RuntimeError("unreachable")

        async def aclose(self):
            return None

    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        FetchResponse(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            provider="http",
            content="hello world content",
        ),
    )
    reg = _reg([http])
    svc = FetchService(registry=reg)
    svc._jev_client = HangingJev()
    svc._jev_max_state_chars = 6000

    route = await svc.fetch(FetchRequest(url="https://example.com"))
    # Returns immediately; fire-and-forget task is left pending.
    assert route.final_response.status_code == 200


@pytest.mark.asyncio
async def test_jev_exception_swallowed(tmp_db):
    class BoomJev:
        name = "boom"

        async def ask(self, q, state):
            raise RuntimeError("jev exploded")

    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        FetchResponse(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            provider="http",
            content="ok content",
        ),
    )
    reg = _reg([http])
    svc = FetchService(registry=reg)
    svc._jev_client = BoomJev()
    await svc.fetch(FetchRequest(url="https://example.com"))
    # No exception propagated.


def test_sensitive_fields_stripped_from_state():
    resp = FetchResponse(
        url="https://user:pass@example.com/page?token=abc&secret=xyz",
        final_url="https://user:pass@example.com/page?token=abc",
        status_code=200,
        provider="http",
        title="Hello",
        content="real body",
        metadata={"raw_html": "<html>", "cookie": "session=123", "authorization": "Bearer xyz"},
    )
    state = jev_shadow.build_fetch_state(resp, None, 6000)
    assert "user:pass" not in str(state)
    assert "token=abc" not in str(state)
    assert "Bearer" not in str(state)
    assert "session=123" not in str(state)
    # Only safe host is present.
    assert state["host"] == "https://example.com"


def test_content_truncated():
    big = "x" * 10000
    resp = FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        provider="http",
        content=big,
    )
    state = jev_shadow.build_fetch_state(resp, None, 1000)
    assert len(state["content_excerpt"]) <= 1100
    assert state["truncated"] is True


@pytest.mark.asyncio
async def test_shadow_recorded_to_sqlite(tmp_db):
    jev_shadow.reset_for_tests()
    client = FakeJevClient()
    resp = FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=403,
        provider="http",
        content="",
    )
    decision = should_escalate_to_browser(resp)
    await jev_shadow.maybe_record_fetch(
        client,
        response=resp,
        rule_decision=decision,
        backend="http",
        actual_route="fast",
        browser_attempted=False,
        browser_success=False,
        max_state_chars=6000,
    )
    rows = jev_store.load_recent(10)
    # Two questions: needs_escalation + result_usable.
    questions = {r["jev_question"] for r in rows}
    assert "needs_escalation" in questions
    assert "result_usable" in questions


@pytest.mark.asyncio
async def test_search_shadow_records(tmp_db):
    jev_shadow.reset_for_tests()
    client = FakeJevClient()
    results = [
        SearchResult(title="Python guide", url="https://python.org", snippet="docs", position=1, backend="bing"),
        SearchResult(title="unrelated", url="https://other.com", snippet="random", position=2, backend="bing"),
    ]
    await jev_shadow.maybe_record_search(
        client,
        query="python tutorial",
        results=results,
        max_results=10,
        max_state_chars=2000,
    )
    rows = jev_store.load_recent(10)
    assert len(rows) == 2
    assert all(r["jev_question"] == "result_relevant" for r in rows)


def test_summary_quadrants(tmp_db):
    jev_shadow.reset_for_tests()
    # Insert a synthetic row where rule says escalate, jev says no.
    jev_store.append_record(
        {
            "timestamp": 1.0,
            "trace_id": "t1",
            "operation": "fetch",
            "jev_question": "needs_escalation",
            "jev_decision": 0,
            "jev_probability": 0.3,
            "jev_confidence": 0.5,
            "jev_latency_ms": 1.0,
            "jev_provider": "fake",
            "jev_error": None,
            "rule_decision": 1,
            "rule_reason": "soft_block",
            "backend": "http",
            "content_length": 100,
        }
    )
    s = jev_store.load_summary()
    assert s["calls"] >= 1
    assert s["quadrants"]["rule_yes/jev_no"] >= 1


@pytest.mark.asyncio
async def test_jev_does_not_change_escalation(tmp_db):
    """Production escalation decision is independent of Jev."""
    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        FetchResponse(
            url="https://example.com",
            final_url="https://example.com",
            status_code=403,
            provider="http",
            content="",
            raw_html="<html><body>cloudflare captcha: please verify you are a human</body></html>",
        ),
    )
    crawl = _FakeProvider(
        "crawl4ai",
        {ProviderCapability.BROWSER},
        FetchResponse(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            provider="crawl4ai",
            content="rendered",
        ),
    )
    reg = _reg([http, crawl])
    svc = FetchService(registry=reg, config=SimpleNamespace(jev_enabled=False))
    route = await svc.fetch(FetchRequest(url="https://example.com"))
    # Rule escalated (403 challenge -> SOFT_BLOCK), browser used, Jev disabled
    # — production unchanged.
    assert route.browser_attempted
    assert route.browser_success
    assert route.final_response.provider == "crawl4ai"


@pytest.mark.asyncio
async def test_jev_enabled_but_noop_does_not_record(tmp_db):
    """When JEV_ENABLED=false, no shadow rows are written."""
    jev_shadow.reset_for_tests()
    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        FetchResponse(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            provider="http",
            content="hello",
        ),
    )
    reg = _reg([http])
    svc = FetchService(registry=reg, config=SimpleNamespace(jev_enabled=False))
    await svc.fetch(FetchRequest(url="https://example.com"))
    # No shadow rows (client is Noop, _fire path skipped).
    assert jev_store.load_recent(10) == []


def test_errors_filter(tmp_db):
    jev_shadow.reset_for_tests()
    jev_store.append_record(
        {
            "timestamp": 1.0,
            "operation": "fetch",
            "jev_question": "needs_escalation",
            "jev_error": "timeout",
            "jev_latency_ms": 1000.0,
        }
    )
    rows = jev_store.load_errors()
    assert any(r["jev_error"] == "timeout" for r in rows)


def test_disagreements_filter(tmp_db):
    jev_shadow.reset_for_tests()
    jev_store.append_record(
        {
            "timestamp": 1.0,
            "operation": "fetch",
            "jev_question": "needs_escalation",
            "jev_decision": 0,
            "rule_decision": 1,
            "rule_reason": "soft_block",
            "backend": "http",
            "jev_error": None,
        }
    )
    rows = jev_store.load_disagreements(10)
    assert len(rows) == 1
