"""Hermetic tests for the v1.5.0 Phase 2.1 corpus drivers.

No real network: providers are stubbed, Jev is a no-op, and corpus files point
at tmp fixtures. The central invariant under test is that the DRIVERS only feed
inputs + flush — every DecisionEvent / SearchResponse is produced by the
production service.
"""

from __future__ import annotations

import json
import types
from pathlib import Path
from unittest import mock

import pytest

from webscout_mcp import decision_store, eval_runners, jev_store
from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.fetch_service import FetchService
from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter
from webscout_mcp.search import SearchResult
from webscout_mcp.search_provider import ProviderHealth, ProviderHealthStatus, SearchResponse
from webscout_mcp.search_service import SearchService, SearchServiceConfig

RUN_ID = "test-run-eval-p21"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubFetchProvider:
    name = "http"

    def __init__(self, response: FetchResponse):
        self._response = response

    async def fetch(self, request):
        return self._response

    async def health(self):
        return ProviderHealth(provider=self.name, status=ProviderHealthStatus.HEALTHY)

    def get_health(self):
        return ProviderHealth(provider=self.name, status=ProviderHealthStatus.HEALTHY)

    async def close(self):
        pass


class StubSearchProvider:
    name = "duckduckgo"

    def __init__(self, results: list[SearchResult]):
        self._results = results

    async def search(self, request):
        return SearchResponse.success(query=request.query, provider=self.name, results=self._results)

    async def health(self):
        return ProviderHealth(provider=self.name, status=ProviderHealthStatus.HEALTHY)

    def get_health(self):
        return ProviderHealth(provider=self.name, status=ProviderHealthStatus.HEALTHY)

    async def close(self):
        pass


def _good_fetch_response(content: str = "", url: str = "https://example.com/page") -> FetchResponse:
    body = content or ("# Example page\n\n" + "word " * 1500)
    return FetchResponse(
        url=url,
        final_url=url,
        status_code=200,
        provider="http",
        title="Example Title",
        content=body,
        content_type="text/html",
        extracted=True,
    )


@pytest.fixture
def isolated_dbs(tmp_path, monkeypatch):
    # Repoint the global stores + process run id to a throwaway run, and let
    # monkeypatch restore every binding on teardown so no state leaks into the
    # rest of the suite.
    import sys

    from webscout_mcp import runtime_context

    decision_db = tmp_path / "decision.db"
    jev_db = tmp_path / "jev.db"
    monkeypatch.setattr(decision_store, "_db_path", decision_db, raising=False)
    monkeypatch.setattr(jev_store, "_db_path", jev_db, raising=False)
    monkeypatch.setattr(runtime_context, "PROCESS_RUN_ID", RUN_ID)
    for mod_name in ("webscout_mcp.fetch_service", "webscout_mcp.search_service", "webscout_mcp.jev_shadow"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "PROCESS_RUN_ID"):
            monkeypatch.setattr(mod, "PROCESS_RUN_ID", RUN_ID)
    monkeypatch.setenv("WEBSCOUT_RUN_ID", RUN_ID)
    monkeypatch.setenv("JEV_RUN_ID", RUN_ID)
    monkeypatch.setenv("JEV_ENABLED", "false")
    yield tmp_path


def _write_fetch_corpus(tmp_path: Path, urls: list[str]) -> Path:
    p = tmp_path / "fetch_urls.json"
    p.write_text(json.dumps({"urls": [{"url": u, "stratum": "test"} for u in urls]}))
    return p


def _write_search_corpus(tmp_path: Path, queries: list[str]) -> Path:
    p = tmp_path / "search_queries.json"
    p.write_text(json.dumps({"queries": [{"query": q, "category": "test"} for q in queries]}))
    return p


def _make_fetch_service(response: FetchResponse) -> FetchService:
    provider = StubFetchProvider(response)
    router = ProviderRouter(
        provider_names=["http"],
        cost_tiers={"http": ProviderCostTier.FREE},
        capabilities={"http": {ProviderCapability.FETCH}},
    )
    registry = ProviderRegistry(router=router)
    registry.register(provider, capabilities={ProviderCapability.FETCH})
    cfg = types.SimpleNamespace(jev_enabled=False, jev_max_state_chars=6000)
    return FetchService(registry=registry, config=cfg)


# ---------------------------------------------------------------------------
# (a) fetch runner uses the production decision path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_runner_records_decision_from_service(isolated_dbs, monkeypatch):
    corpus = _write_fetch_corpus(isolated_dbs, ["https://example.com/page"])
    monkeypatch.setattr(eval_runners, "_FETCH_CORPUS_PATH", corpus)

    fetch_service = _make_fetch_service(_good_fetch_response())

    calls: list[dict] = []
    from webscout_mcp import decision_adapter

    real = decision_adapter.record_fetch_decision

    def spy(**kwargs):
        import traceback

        # The call must have originated inside the production service (a
        # fetch_service.py frame in the stack), never from the eval driver.
        frames = [f.filename for f in traceback.extract_stack()]
        calls.append({"in_service": any("webscout_mcp/fetch_service.py" in f for f in frames)})
        return real(**kwargs)

    with mock.patch("webscout_mcp.decision_adapter.record_fetch_decision", side_effect=spy) as m:
        summary = await eval_runners.run_fetch_corpus(fetch_service, RUN_ID, limit=1)

    # Driver returned the human-pack list with documented keys.
    assert summary["total"] == 1
    row = summary["results"][0]
    for key in ("url", "trace_id", "status", "status_code", "chars", "title", "excerpt"):
        assert key in row
    assert row["status"] == "success"
    assert row["status_code"] == 200
    assert row["trace_id"]  # production trace correlated

    # record_fetch_decision WAS called, and always from inside the service.
    assert m.call_count >= 1
    assert calls, "service never recorded a fetch decision"
    assert all(c["in_service"] for c in calls)

    # A DecisionEvent exists in the production decision DB, stamped by the service.
    events = decision_store.load_events(domain="fetch", limit=10)
    events = [e for e in events if e["run_id"] == RUN_ID]
    assert events, "service must have recorded a fetch DecisionEvent"
    ev = events[0]
    assert ev["trace_id"] == row["trace_id"]
    # Action originates from the production classifier (a 200+ rich page -> ACCEPT).
    assert ev["deterministic_action"] == "ACCEPT"
    assert ev["deterministic_reason"]


# ---------------------------------------------------------------------------
# (b) search runner uses the production service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_runner_records_decision_from_service(isolated_dbs, monkeypatch):
    corpus = _write_search_corpus(isolated_dbs, ["python urllib.parse docs"])
    monkeypatch.setattr(eval_runners, "_SEARCH_CORPUS_PATH", corpus)

    results = [
        SearchResult(title="R1", url="https://example.com/1", snippet="s1", position=1, backend="ddg"),
        SearchResult(title="R2", url="https://example.com/2", snippet="s2", position=2, backend="ddg"),
    ]
    svc = SearchService(providers=[StubSearchProvider(results)], config=SearchServiceConfig())
    svc.jev_client = None

    from webscout_mcp import decision_adapter

    with mock.patch(
        "webscout_mcp.decision_adapter.record_search_decision",
        wraps=decision_adapter.record_search_decision,
    ) as m:
        summary = await eval_runners.run_search_corpus(svc, RUN_ID, limit=1)

    assert summary["total"] == 1
    assert summary["result_rows"] == 2
    row = summary["results"][0]
    for key in ("query", "trace_id", "rows"):
        assert key in row
    assert row["rows"][0]["position"] == 1
    assert row["rows"][0]["title"] == "R1"

    # The service recorded a search DecisionEvent (driver built no response).
    assert m.call_count >= 1
    events = [e for e in decision_store.load_events(domain="search", limit=10) if e["run_id"] == RUN_ID]
    assert events
    assert events[0]["trace_id"] == row["trace_id"]


# ---------------------------------------------------------------------------
# (c) browser counterfactual records raw facts, no browser_required label
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_counterfactual_raw_facts(isolated_dbs, monkeypatch):
    corpus = _write_fetch_corpus(isolated_dbs, ["https://example.com/a", "https://example.com/b"])
    monkeypatch.setattr(eval_runners, "_FETCH_CORPUS_PATH", corpus)

    primary = _good_fetch_response(content="short text", url="https://example.com/a")
    browser = FetchResponse(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=200,
        provider="crawl4ai",
        title="Browser Title",
        content="browser rendered content " * 500,
        content_type="text/html",
        extracted=True,
    )

    http_provider = StubFetchProvider(primary)
    http_provider.name = "http"
    browser_provider = StubFetchProvider(browser)
    browser_provider.name = "crawl4ai"

    router = ProviderRouter(
        provider_names=["http", "crawl4ai"],
        cost_tiers={"http": ProviderCostTier.FREE, "crawl4ai": ProviderCostTier.PAID},
        capabilities={
            "http": {ProviderCapability.FETCH},
            "crawl4ai": {ProviderCapability.BROWSER},
        },
    )
    registry = ProviderRegistry(router=router)
    registry.register(http_provider, capabilities={ProviderCapability.FETCH})
    registry.register(browser_provider, capabilities={ProviderCapability.BROWSER})
    cfg = types.SimpleNamespace(jev_enabled=False, jev_max_state_chars=6000)
    fetch_service = FetchService(registry=registry, config=cfg)

    services = {
        "fetch_service": fetch_service,
        "registry": registry,
        "eval_dir": isolated_dbs,
    }

    cases = await eval_runners.run_browser_counterfactual(services, RUN_ID, limit=2)

    assert len(cases) == 2
    for c in cases:
        assert c["run_id"] == RUN_ID
        assert c["case_id"].startswith("cf:")
        assert c["source_trace_id"]  # production fetch trace correlated
        for f in (
            "url",
            "primary_status",
            "browser_status",
            "primary_chars",
            "browser_chars",
            "gain",
            "primary_extraction_success",
            "browser_extraction_success",
        ):
            assert f in c
        # CRITICAL: no inference of "browser required" from a positive gain.
        assert "browser_required" not in c
        assert c["gain"] == c["browser_chars"] - c["primary_chars"]

    # Artifact JSONL was written and parses back to the same rows.
    artifact = isolated_dbs / "browser-counterfactual.jsonl"
    assert artifact.exists()
    lines = [json.loads(ln) for ln in artifact.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    assert all("browser_required" not in ln for ln in lines)


# ---------------------------------------------------------------------------
# (d) result-list key shape sanity (error path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_runner_error_row_keys(isolated_dbs, monkeypatch):
    corpus = _write_fetch_corpus(isolated_dbs, ["https://example.com/boom"])
    monkeypatch.setattr(eval_runners, "_FETCH_CORPUS_PATH", corpus)

    class Boom(StubFetchProvider):
        async def fetch(self, request):
            raise RuntimeError("network down")

    router = ProviderRouter(
        provider_names=["http"],
        cost_tiers={"http": ProviderCostTier.FREE},
        capabilities={"http": {ProviderCapability.FETCH}},
    )
    registry = ProviderRegistry(router=router)
    registry.register(Boom(_good_fetch_response()), capabilities={ProviderCapability.FETCH})
    cfg = types.SimpleNamespace(jev_enabled=False, jev_max_state_chars=6000)
    svc = FetchService(registry=registry, config=cfg)

    summary = await eval_runners.run_fetch_corpus(svc, RUN_ID, limit=1)
    row = summary["results"][0]
    assert row["status"] == "error"
    for key in ("url", "trace_id", "status", "status_code", "chars", "title", "excerpt"):
        assert key in row
