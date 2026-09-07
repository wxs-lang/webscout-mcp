"""Startup self-check for WebScout MCP.

Runs lightweight checks at server startup to verify core tools are usable.
Results are logged and available via search_health tool.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .logging_config import get_logger
from .search_provider import SearchRequest

log = get_logger(__name__)


@dataclass
class CheckResult:
    """Result of a single startup check."""

    name: str
    passed: bool
    duration_ms: float = 0.0
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class StartupReport:
    """Complete startup self-check report."""

    started_at: float
    completed_at: float = 0.0
    checks: list[CheckResult] = field(default_factory=list)
    overall_passed: bool = True

    @property
    def duration_ms(self) -> float:
        return (self.completed_at - self.started_at) * 1000 if self.completed_at else 0.0

    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_passed": self.overall_passed,
            "duration_ms": round(self.duration_ms, 2),
            "passed": self.passed_count,
            "failed": self.failed_count,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "duration_ms": round(c.duration_ms, 2),
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


class StartupSelfCheck:
    """Run startup checks to verify core tools are usable."""

    def __init__(self, search_engine=None, search_service=None, fetcher=None, cache=None):
        self.search_engine = search_engine
        self.search_service = search_service
        self.fetcher = fetcher
        self.cache = cache
        self._report: StartupReport | None = None

    @property
    def report(self) -> StartupReport | None:
        return self._report

    async def run_all(self) -> StartupReport:
        """Run all startup checks."""
        report = StartupReport(started_at=time.time())
        log.info("Running startup self-check...")

        checks = [
            self._check_cache,
            self._check_search_engine,
            self._check_search_service,
            self._check_fetcher,
            self._check_search_quick,
        ]

        for check_fn in checks:
            try:
                result = await check_fn()
                report.checks.append(result)
                if not result.passed:
                    report.overall_passed = False
                    log.warning(f"Startup check FAILED: {result.name} - {result.message}")
                else:
                    log.info(f"Startup check passed: {result.name} ({result.duration_ms:.1f}ms)")
            except Exception as e:
                result = CheckResult(
                    name=check_fn.__name__.replace("_check_", ""),
                    passed=False,
                    message=f"Exception: {e}",
                )
                report.checks.append(result)
                report.overall_passed = False
                log.error(f"Startup check exception: {result.name} - {e}")

        report.completed_at = time.time()
        self._report = report

        if report.overall_passed:
            log.info(
                f"Startup self-check PASSED: {report.passed_count}/{len(report.checks)} "
                f"checks in {report.duration_ms:.1f}ms"
            )
        else:
            log.warning(
                f"Startup self-check COMPLETED WITH FAILURES: "
                f"{report.passed_count} passed, {report.failed_count} failed "
                f"in {report.duration_ms:.1f}ms"
            )

        return report

    async def _check_cache(self) -> CheckResult:
        """Check if cache is accessible."""
        start = time.time()
        if self.cache is None:
            return CheckResult("cache", False, message="Cache not initialized")
        try:
            stats = self.cache.stats() if hasattr(self.cache, "stats") else self.cache.get_stats()
            return CheckResult(
                "cache",
                True,
                duration_ms=(time.time() - start) * 1000,
                message=f"Cache OK, {stats.get('total_entries', 0)} entries",
                details=stats,
            )
        except Exception as e:
            return CheckResult("cache", False, message=f"Cache error: {e}")

    async def _check_search_engine(self) -> CheckResult:
        """Check if legacy SearchEngine is initialized."""
        start = time.time()
        if self.search_engine is None:
            return CheckResult("search_engine", False, message="SearchEngine not initialized")
        try:
            backends = getattr(self.search_engine, "backends", [])
            return CheckResult(
                "search_engine",
                True,
                duration_ms=(time.time() - start) * 1000,
                message=f"SearchEngine OK, {len(backends)} backends",
            )
        except Exception as e:
            return CheckResult("search_engine", False, message=f"SearchEngine error: {e}")

    async def _check_search_service(self) -> CheckResult:
        """Check if new SearchService is initialized."""
        start = time.time()
        if self.search_service is None:
            return CheckResult(
                "search_service",
                True,
                duration_ms=(time.time() - start) * 1000,
                message="SearchService not initialized (using legacy SearchEngine fallback)",
            )
        try:
            providers = getattr(self.search_service, "providers", [])
            return CheckResult(
                "search_service",
                True,
                duration_ms=(time.time() - start) * 1000,
                message=f"SearchService OK, {len(providers)} providers",
            )
        except Exception as e:
            return CheckResult("search_service", False, message=f"SearchService error: {e}")

    async def _check_fetcher(self) -> CheckResult:
        """Check if Fetcher is initialized."""
        start = time.time()
        if self.fetcher is None:
            return CheckResult("fetcher", False, message="Fetcher not initialized")
        return CheckResult(
            "fetcher",
            True,
            duration_ms=(time.time() - start) * 1000,
            message="Fetcher initialized",
        )

    async def _check_search_quick(self) -> CheckResult:
        """Quick search connectivity check (non-blocking, 5s timeout)."""
        start = time.time()
        search_obj = self.search_service or self.search_engine
        if search_obj is None:
            return CheckResult("search_connectivity", False, message="No search object available")

        try:
            if hasattr(search_obj, "search"):
                # Support both SearchService (SearchRequest) and SearchEngine (kwargs)
                try:
                    request = SearchRequest(query="test", max_results=1)
                    result = await asyncio.wait_for(
                        search_obj.search(request),
                        timeout=5.0,
                    )
                except TypeError:
                    # Fallback for old SearchEngine API
                    result = await asyncio.wait_for(
                        search_obj.search("test", max_results=1),
                        timeout=5.0,
                    )
                results = result.get("results", []) if isinstance(result, dict) else []
                return CheckResult(
                    "search_connectivity",
                    True,
                    duration_ms=(time.time() - start) * 1000,
                    message=f"Search OK, {len(results)} results",
                )
            else:
                return CheckResult(
                    "search_connectivity",
                    True,
                    duration_ms=(time.time() - start) * 1000,
                    message="Search object available (no async search method, skipped live check)",
                )
        except asyncio.TimeoutError:
            return CheckResult(
                "search_connectivity",
                False,
                duration_ms=(time.time() - start) * 1000,
                message="Search timed out after 5s",
            )
        except Exception as e:
            return CheckResult(
                "search_connectivity",
                False,
                duration_ms=(time.time() - start) * 1000,
                message=f"Search error: {e}",
            )
