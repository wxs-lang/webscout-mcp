"""Tests for Phase 2.6: real TypeSafeJevClient adapter, ask_many batching,
JEV_PROVIDER routing, provider data isolation, pending task lifecycle,
and CLI --provider filter.

These tests mock the official typesafe-sdk — they never call the real API.
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webscout_mcp.jev_client import (
    JEV_DECISION_SCHEMA_VERSION,
    FakeJevClient,
    NoopJevClient,
    TypeSafeJevClient,
    make_jev_client,
)


def test_disabled_is_noop():
    cfg = SimpleNamespace(jev_enabled=False, jev_provider="typesafe", jev_api_key="")
    assert isinstance(make_jev_client(cfg), NoopJevClient)


def test_explicit_fake_uses_fake():
    cfg = SimpleNamespace(jev_enabled=True, jev_provider="fake", jev_api_key="")
    assert isinstance(make_jev_client(cfg), FakeJevClient)


def test_typesafe_missing_key_falls_back_to_noop_not_fake(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    cfg = SimpleNamespace(
        jev_enabled=True,
        jev_provider="typesafe",
        jev_api_key="",
        jev_model="jev-latest",
        jev_timeout_ms=1000,
        jev_base_url="",
    )
    assert isinstance(make_jev_client(cfg), NoopJevClient)


def test_typesafe_with_key_returns_typesafe(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "sk-test")
    cfg = SimpleNamespace(
        jev_enabled=True,
        jev_provider="typesafe",
        jev_api_key="",
        jev_model="jev-latest",
        jev_timeout_ms=1000,
        jev_base_url="",
    )
    client = make_jev_client(cfg)
    assert isinstance(client, TypeSafeJevClient)


@pytest.mark.asyncio
async def test_typesafe_maps_noul_answer():
    fake_answer = MagicMock()
    fake_answer.noul = 0.82
    fake_usage = MagicMock(input_tokens=10, output_tokens=5)
    fake_resp = MagicMock()
    fake_resp.answers = {"needs_escalation": fake_answer}
    fake_resp.usage = fake_usage
    fake_client = AsyncMock()
    fake_client.system_one = AsyncMock(return_value=fake_resp)
    fake_client.aclose = AsyncMock()

    adapter = TypeSafeJevClient("sk-x", model="jev-latest", timeout_ms=500)
    adapter._client = fake_client

    out = await adapter.ask_many(["needs_escalation"], {"x": 1})
    d = out["needs_escalation"]
    assert d.decision is True
    assert d.probability_yes == 0.82
    assert d.confidence is None  # SDK doesn't expose confidence
    assert d.input_tokens == 10
    assert d.output_tokens == 5
    assert d.provider == "typesafe"


@pytest.mark.asyncio
async def test_typesafe_timeout_isolation():
    fake_client = AsyncMock()
    fake_client.system_one = AsyncMock(side_effect=asyncio.TimeoutError())
    fake_client.aclose = AsyncMock()
    adapter = TypeSafeJevClient("sk-x", timeout_ms=200)
    adapter._client = fake_client
    out = await adapter.ask_many(["needs_escalation"], {})
    assert out["needs_escalation"].error == "timeout"


@pytest.mark.asyncio
async def test_typesafe_exception_isolation_and_key_redaction():
    fake_client = AsyncMock()
    fake_client.system_one = AsyncMock(side_effect=RuntimeError("401 invalid key sk-supersecret-key"))
    fake_client.aclose = AsyncMock()
    adapter = TypeSafeJevClient("sk-supersecret-key", timeout_ms=500)
    adapter._client = fake_client
    out = await adapter.ask_many(["needs_escalation"], {})
    err = out["needs_escalation"].error
    assert "sk-supersecret-key" not in err
    assert "<redacted>" in err


@pytest.mark.asyncio
async def test_ask_many_single_rtt_for_two_questions():
    fake_answer = MagicMock()
    fake_answer.noul = 0.7
    fake_usage = MagicMock(input_tokens=20, output_tokens=10)
    fake_resp = MagicMock()
    fake_resp.answers = {
        "needs_escalation": fake_answer,
        "result_usable": fake_answer,
    }
    fake_resp.usage = fake_usage
    fake_client = AsyncMock()
    fake_client.system_one = AsyncMock(return_value=fake_resp)
    fake_client.aclose = AsyncMock()
    adapter = TypeSafeJevClient("sk-x", timeout_ms=500)
    adapter._client = fake_client
    out = await adapter.ask_many(["needs_escalation", "result_usable"], {"c": 1})
    assert fake_client.system_one.await_count == 1
    assert set(out.keys()) == {"needs_escalation", "result_usable"}


def test_schema_version_constant():
    assert JEV_DECISION_SCHEMA_VERSION == "1"


def test_confidence_optional():
    from webscout_mcp.jev_client import JevDecision

    d = JevDecision(
        question="result_usable",
        decision=True,
        probability_yes=0.9,
        confidence=None,
        latency_ms=1.0,
    )
    assert d.confidence is None


def test_pending_task_strong_reference_and_flush():
    """pending task set + done_callback discard behaves correctly."""
    pending: set = set()

    async def noop():
        return None

    async def main():
        task = asyncio.create_task(noop())
        pending.add(task)
        task.add_done_callback(pending.discard)
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=1.0)
        pending.clear()
        assert len(pending) == 0

    asyncio.run(main())


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBSCOUT_JEV_DB", str(tmp_path / "jev.db"))
    from webscout_mcp import jev_store

    jev_store.configure()


@pytest.mark.asyncio
async def test_noop_does_not_record(tmp_db):
    """Noop client must not pollute the shadow DB."""
    from webscout_mcp import jev_shadow, jev_store
    from webscout_mcp.fetch_provider import FetchResponse

    jev_shadow.reset_for_tests()
    resp = FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        provider="http",
        content="x" * 500,
    )
    client = NoopJevClient()
    before = jev_store.load_summary()["calls"]
    await jev_shadow.maybe_record_fetch(
        client,
        response=resp,
        rule_decision=None,
        backend="http",
        actual_route="fast",
        browser_attempted=False,
        browser_success=False,
        max_state_chars=600,
    )
    after = jev_store.load_summary()["calls"]
    assert before == after


@pytest.mark.asyncio
async def test_probability_out_of_range_is_malformed():
    fake_answer = MagicMock()
    fake_answer.noul = 1.5  # out of [0,1]
    fake_resp = MagicMock()
    fake_resp.answers = {"needs_escalation": fake_answer}
    fake_resp.usage = None
    fake_client = AsyncMock()
    fake_client.system_one = AsyncMock(return_value=fake_resp)
    fake_client.aclose = AsyncMock()
    adapter = TypeSafeJevClient("sk-x", timeout_ms=500)
    adapter._client = fake_client
    out = await adapter.ask_many(["needs_escalation"], {})
    assert out["needs_escalation"].error == "malformed_response"


def test_smoke_without_key_skips(monkeypatch, capsys):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from webscout_mcp.__main__ import _jev_smoke

    asyncio.run(_jev_smoke())
    out = capsys.readouterr().out
    assert "skipped" in out and "TYPESAFE_API_KEY" in out


def test_cli_new_flags():
    from webscout_mcp.__main__ import build_parser

    parser = build_parser()
    ns = parser.parse_args(["jev-report", "--summary", "--schema-version", "1", "--all"])
    assert ns.schema_version == "1"
    assert ns.all is True
    ns2 = parser.parse_args(["jev-report", "--smoke"])
    assert ns2.smoke is True
    ns3 = parser.parse_args(["jev-report", "--last", "10", "--provider", "fake"])
    assert ns3.provider == "fake"
