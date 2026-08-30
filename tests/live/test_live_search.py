"""
Live network tests for search and fetch functionality.

These tests run against real search engines and websites to verify
that the system works in real-world conditions. They are NOT run
in normal CI - they are run on a schedule (daily) and manually.

Metrics collected:
- Success rate
- Empty result rate
- Fallback rate
- P50/P95 latency
- Error types (403, 429, timeout, etc.)
- Provider distribution

Test categories:
1. TestLiveSearch - 15 queries (10 English + 5 Chinese) x 2 search paths
2. TestLiveFetch - 5 real URLs using WebScout's own Fetcher (not raw httpx)
3. TestLiveFallback - Force Bing failure -> verify DuckDuckGo real network fallback
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from webscout_mcp.config import Config
from webscout_mcp.fetcher import Fetcher
from webscout_mcp.search import SearchEngine
from webscout_mcp.search_provider import SearchProvider, SearchRequest, SearchResponse
from webscout_mcp.search_service import SearchService, SearchServiceConfig

# ============================================================
# Test queries - fixed set for consistent measurement
# ============================================================
SEARCH_QUERIES = [
    # English queries (10)
    "python asyncio documentation",
    "github actions workflow syntax",
    "postgresql create index best practices",
    "fastapi tutorial 2024",
    "docker compose networking",
    "kubernetes pod lifecycle",
    "redis caching strategies",
    "elasticsearch query DSL",
    "nginx reverse proxy configuration",
    "linux systemd service example",
    # Chinese queries (5)
    "Python 异步编程教程",
    "GitHub Actions 工作流配置",
    "PostgreSQL 索引优化",
    "FastAPI 快速入门",
    "Docker 网络配置",
]

FETCH_URLS = [
    "https://docs.python.org/3/library/asyncio.html",
    "https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions",
    "https://www.postgresql.org/docs/current/sql-createindex.html",
    "https://fastapi.tiangolo.com/tutorial/",
    "https://docs.docker.com/compose/networking/",
]

# Results directory - can be overridden via env var for CI
RESULTS_DIR = Path(os.environ.get("LIVE_TEST_RESULTS_DIR", "live-test-results"))


# ============================================================
# Metrics collection
# ============================================================
@dataclass
class TestResult:
    """Result of a single test."""

    name: str
    success: bool
    latency_ms: float
    error: str | None = None
    result_count: int = 0
    provider: str | None = None


@dataclass
class LiveTestReport:
    """Report of all live tests."""

    timestamp: float = field(default_factory=time.time)
    search_results: list[TestResult] = field(default_factory=list)
    fetch_results: list[TestResult] = field(default_factory=list)
    fallback_results: list[TestResult] = field(default_factory=list)

    def add_search_result(self, result: TestResult) -> None:
        self.search_results.append(result)

    def add_fetch_result(self, result: TestResult) -> None:
        self.fetch_results.append(result)

    def add_fallback_result(self, result: TestResult) -> None:
        self.fallback_results.append(result)

    def _calculate_stats(self, results: list[TestResult]) -> dict[str, Any]:
        if not results:
            return {"count": 0}

        successes = [r for r in results if r.success]
        failures = [r for r in results if not r.success]
        latencies = sorted([r.latency_ms for r in results])

        p50 = latencies[len(latencies) // 2] if latencies else 0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

        error_types: dict[str, int] = {}
        for r in failures:
            error_type = r.error or "unknown"
            error_types[error_type] = error_types.get(error_type, 0) + 1

        providers: dict[str, int] = {}
        for r in successes:
            if r.provider:
                providers[r.provider] = providers.get(r.provider, 0) + 1

        return {
            "count": len(results),
            "success_count": len(successes),
            "failure_count": len(failures),
            "success_rate": round(len(successes) / len(results) * 100, 1),
            "p50_latency_ms": round(p50, 1),
            "p95_latency_ms": round(p95, 1),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
            "error_types": error_types,
            "providers": providers,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "datetime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp)),
            "search": self._calculate_stats(self.search_results),
            "fetch": self._calculate_stats(self.fetch_results),
            "fallback": self._calculate_stats(self.fallback_results),
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


# ============================================================
# Mock provider for forced failure testing
# ============================================================
class AlwaysFailingProvider(SearchProvider):
    """A SearchProvider that always fails - used to test fallback to real providers."""

    def __init__(self, name: str = "failing-mock"):
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            results=[],
            provider=self._name,
            is_success=False,
            error_message=f"Forced failure for fallback testing (provider={self._name})",
            error_code="FORCED_FAILURE",
            retryable=False,
            latency_ms=0.0,
        )

    async def health(self) -> dict[str, Any]:
        return {"status": "unhealthy", "reason": "Always failing mock provider"}


# ============================================================
# Live tests
# ============================================================
# Live tests are excluded from normal CI via --ignore=tests/live
# Run them manually with: pytest tests/live/


@pytest.fixture(scope="session")
def search_engine():
    """Create a SearchEngine instance for live tests."""
    config = Config.from_env()
    config.ensure_dirs()
    return SearchEngine(config, None)


@pytest.fixture(scope="session")
def search_service():
    """Create a SearchService instance for live tests."""
    config = Config.from_env()
    config.ensure_dirs()
    from webscout_mcp.search_service import create_search_service_from_config

    return create_search_service_from_config(config, None)


@pytest.fixture(scope="session")
def fetcher():
    """Create a WebScout Fetcher instance for live fetch tests.

    This uses the project's OWN Fetcher class, not raw httpx,
    to test the real product path: Fetcher -> cache/security/extraction.
    """
    config = Config.from_env()
    config.ensure_dirs()
    return Fetcher(config, None)


@pytest.fixture(scope="session")
def fallback_search_service():
    """Create a SearchService with forced Bing failure -> real DuckDuckGo fallback.

    This tests the REAL fallback path: when Bing is unavailable,
    does SearchService successfully fall back to DuckDuckGo and
    return real network results?
    """
    from webscout_mcp.search import DuckDuckGoHTMLBackend
    from webscout_mcp.search_provider_adapter import SearchBackendAdapter

    config = Config.from_env()
    config.ensure_dirs()

    # First provider: always-failing mock (simulates Bing being down)
    failing_bing = AlwaysFailingProvider(name="bing-forced-down")

    # Second provider: REAL DuckDuckGo backend
    ddg_backend = DuckDuckGoHTMLBackend(config)
    real_ddg = SearchBackendAdapter(ddg_backend, name="duckduckgo")

    service_config = SearchServiceConfig(
        max_retries=1,
        circuit_failure_threshold=3,
        circuit_recovery_time=30,
        request_timeout=30.0,
    )

    return SearchService(providers=[failing_bing, real_ddg], config=service_config)


@pytest.fixture(scope="session")
def live_report():
    """Create a LiveTestReport instance."""
    return LiveTestReport()


class TestLiveSearch:
    """Test search against real search engines - all 15 queries (10 English + 5 Chinese)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", SEARCH_QUERIES)
    async def test_search_engine_live(self, search_engine, live_report, query):
        """Test old SearchEngine against real search engines."""
        start_time = time.time()
        try:
            results = await search_engine.search(
                query=query,
                max_results=5,
                region="wt-wt",
                safe_search=False,
            )
            latency_ms = (time.time() - start_time) * 1000
            success = len(results) > 0
            result = TestResult(
                name=f"SearchEngine: {query}",
                success=success,
                latency_ms=latency_ms,
                result_count=len(results),
                provider=results[0].backend if results else None,
            )
            live_report.add_search_result(result)
            assert success, f"No results for query: {query}"
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            result = TestResult(
                name=f"SearchEngine: {query}",
                success=False,
                latency_ms=latency_ms,
                error=str(e)[:100],
            )
            live_report.add_search_result(result)
            pytest.fail(f"Search failed for '{query}': {e}")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", SEARCH_QUERIES)
    async def test_search_service_live(self, search_service, live_report, query):
        """Test new SearchService against real search engines."""
        start_time = time.time()
        try:
            request = SearchRequest(query=query, max_results=5)
            response = await search_service.search(request)
            latency_ms = (time.time() - start_time) * 1000
            result = TestResult(
                name=f"SearchService: {query}",
                success=response.is_success,
                latency_ms=latency_ms,
                result_count=len(response.results),
                provider=response.provider,
                error=response.error_message,
            )
            live_report.add_search_result(result)
            assert response.is_success, f"Search failed for '{query}': {response.error_message}"
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            result = TestResult(
                name=f"SearchService: {query}",
                success=False,
                latency_ms=latency_ms,
                error=str(e)[:100],
            )
            live_report.add_search_result(result)
            pytest.fail(f"Search failed for '{query}': {e}")


class TestLiveFetch:
    """Test fetch against real websites using WebScout's own Fetcher (not raw httpx).

    This tests the REAL product path:
    MCP client -> web_fetch tool -> Fetcher.fetch() -> cache/security/extraction -> result
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url", FETCH_URLS)
    async def test_fetch_url_live(self, fetcher, live_report, url):
        """Test fetching a real URL with WebScout's Fetcher."""
        start_time = time.time()
        try:
            result = await fetcher.fetch(
                url=url,
                extract=True,
                output_format="markdown",
                max_chars=5000,
                bypass_cache=True,
            )
            latency_ms = (time.time() - start_time) * 1000

            # Check if fetch was successful and returned meaningful content
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
            content = result_dict.get("content", "") or result_dict.get("raw_html", "") or ""
            status = result_dict.get("status_code", 0) or result_dict.get("status", 0)

            success = len(content) > 100 and (status == 200 or status == 0)

            test_result = TestResult(
                name=f"Fetch: {url}",
                success=success,
                latency_ms=latency_ms,
                result_count=len(content),
                provider=f"WebScout Fetcher (status={status})",
                error=None if success else f"Status {status} or content too short ({len(content)} chars)",
            )
            live_report.add_fetch_result(test_result)
            assert success, f"Failed to fetch {url}: status={status}, content length={len(content)}"
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            test_result = TestResult(
                name=f"Fetch: {url}",
                success=False,
                latency_ms=latency_ms,
                error=str(e)[:100],
            )
            live_report.add_fetch_result(test_result)
            pytest.fail(f"Fetch failed for '{url}': {e}")


class TestLiveFallback:
    """Test real network fallback when primary provider is forced to fail.

    This is the most valuable live test: it proves that when Bing is down,
    SearchService actually attempts fallback to DuckDuckGo.

    Note: We do NOT assert that DuckDuckGo must succeed, because DuckDuckGo
    may also be rate-limited or blocked in CI environments. Instead, we verify
    that:
    1. The fallback logic was actually triggered (total_fallbacks > 0)
    2. The system handled the failure gracefully (no crash)
    3. If DuckDuckGo succeeds, verify provider and results
    4. If DuckDuckGo also fails, record it as a real network finding
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", SEARCH_QUERIES[:5])  # Use 5 queries for speed
    async def test_bing_failure_ddg_fallback_live(self, fallback_search_service, live_report, query):
        """Test that forced Bing failure triggers DuckDuckGo fallback attempt."""
        start_time = time.time()
        fallbacks_before = fallback_search_service.total_fallbacks

        try:
            request = SearchRequest(query=query, max_results=5)
            response = await fallback_search_service.search(request)
            latency_ms = (time.time() - start_time) * 1000

            # Key verification: fallback logic was triggered
            fallbacks_after = fallback_search_service.total_fallbacks
            fallback_triggered = fallbacks_after > fallbacks_before

            # If DuckDuckGo succeeded, verify provider and results
            ddg_succeeded = response.is_success and response.provider == "duckduckgo"

            # Test passes if fallback was triggered (regardless of DDG success)
            # This is the real value: proving the system attempts fallback
            success = fallback_triggered

            test_result = TestResult(
                name=f"Fallback (Bing down -> DDG): {query}",
                success=success,
                latency_ms=latency_ms,
                result_count=len(response.results),
                provider=response.provider,
                error=(
                    None if success else f"Fallback not triggered (fallbacks: {fallbacks_before} -> {fallbacks_after})"
                ),
            )
            live_report.add_fallback_result(test_result)

            # Primary assertion: fallback was triggered
            assert fallback_triggered, (
                f"Fallback not triggered for '{query}': fallbacks {fallbacks_before} -> {fallbacks_after}"
            )

            # Additional info: log whether DDG actually succeeded
            if ddg_succeeded:
                print(f"✅ DuckDuckGo fallback succeeded for '{query}' ({len(response.results)} results)")
            else:
                print(
                    f"⚠️  DuckDuckGo fallback also failed for '{query}': "
                    f"{response.error_message or 'unknown error'} "
                    f"(this is a real network finding, not a test failure)"
                )

        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            test_result = TestResult(
                name=f"Fallback (Bing down -> DDG): {query}",
                success=False,
                latency_ms=latency_ms,
                error=str(e)[:100],
            )
            live_report.add_fallback_result(test_result)
            pytest.fail(f"Fallback test crashed for '{query}': {e}")


def test_save_live_report(live_report):
    """Save the live test report to the results directory for artifact upload."""
    # Save to the results directory that the workflow uploads as artifact
    report_path = RESULTS_DIR / "live_report.json"
    live_report.save(report_path)

    assert report_path.exists(), f"Report not saved to {report_path}"

    data = json.loads(report_path.read_text())
    assert "search" in data, "Report missing 'search' key"
    assert "fetch" in data, "Report missing 'fetch' key"
    assert "fallback" in data, "Report missing 'fallback' key"

    print(f"\n✅ Live Test Report saved to: {report_path}")
    print(f"   Search tests: {data['search'].get('count', 0)}")
    print(f"   Fetch tests: {data['fetch'].get('count', 0)}")
    print(f"   Fallback tests: {data['fallback'].get('count', 0)}")
    print(f"   Search success rate: {data['search'].get('success_rate', 'N/A')}%")
    print(f"   Fetch success rate: {data['fetch'].get('success_rate', 'N/A')}%")
    print(f"   Fallback success rate: {data['fallback'].get('success_rate', 'N/A')}%")
    print("\nFull report:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
