"""
Live network tests for search functionality.

These tests run against real search engines and websites to verify
that the system works in real-world conditions. They are NOT run
in normal CI - they are run on a schedule (daily) and manually.

Metrics collected:
- Success rate
- Empty result rate
- Fallback rate
- P50/P95 latency
- Error types (403, 429, timeout, etc.)
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from webscout_mcp.config import Config
from webscout_mcp.search import SearchEngine
from webscout_mcp.search_provider import SearchRequest
from webscout_mcp.search_service import create_search_service_from_config

# ============================================================
# Test queries - fixed set for consistent measurement
# ============================================================

SEARCH_QUERIES = [
    # English queries
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
    # Chinese queries
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

    def add_search_result(self, result: TestResult) -> None:
        self.search_results.append(result)

    def add_fetch_result(self, result: TestResult) -> None:
        self.fetch_results.append(result)

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
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


# ============================================================
# Live tests
# ============================================================

# Live tests are excluded from normal CI via --ignore=tests/live
# Run them manually with: pytest tests/live/ --run-live


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
    return create_search_service_from_config(config, None)


@pytest.fixture(scope="session")
def live_report():
    """Create a LiveTestReport instance."""
    return LiveTestReport()


class TestLiveSearch:
    """Test search against real search engines."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", SEARCH_QUERIES[:5])  # Run subset for speed
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
    @pytest.mark.parametrize("query", SEARCH_QUERIES[:5])
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


def test_save_live_report(live_report, tmp_path):
    """Save the live test report."""
    report_path = tmp_path / "live_report.json"
    live_report.save(report_path)
    assert report_path.exists()
    data = json.loads(report_path.read_text())
    assert "search" in data
    assert "fetch" in data
    print(f"\nLive Test Report saved to: {report_path}")
    print(json.dumps(data, indent=2, ensure_ascii=False))
