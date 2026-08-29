"""
System-level fault injection tests.

These tests verify fault tolerance at the SYSTEM level, not just the
CircuitBreaker class. Faults are injected through the SearchProvider
interface (HTTP 429, timeout, DNS failure, etc.), and we verify that
the orchestration layer correctly:
  1. Detects the failure
  2. Falls back to another provider
  3. Opens the circuit after repeated failures
  4. Recovers after the reset timeout

This is different from test_fault_injection.py, which tests the
BackendHealth and SearchHealthManager classes in isolation.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.search import SearchResult
from webscout_mcp.search_health import SearchHealthManager
from webscout_mcp.search_provider import (
    SearchProvider,
    SearchRequest,
    SearchResponse,
)

# ============================================================
# Fake Search Providers for fault injection
# ============================================================


class FakeSearchProvider(SearchProvider):
    """A configurable fake search provider for fault injection.

    Can be configured to:
      - Return successful results
      - Return empty results
      - Raise specific exceptions (timeout, connection error, etc.)
      - Return error responses with specific error codes
      - Fail for N requests, then succeed
    """

    def __init__(
        self,
        name: str,
        behavior: str = "success",
        fail_count: int = 0,
        error_code: StandardErrorCode | None = None,
        error_message: str = "Simulated failure",
        delay: float = 0.0,
        num_results: int = 5,
    ):
        # Must set _name before super().__init__() because parent calls self.name
        self._name = name
        super().__init__(config=None)
        self.behavior = behavior
        self.fail_count = fail_count
        self.error_code = error_code or StandardErrorCode.SEARCH_BACKEND_FAILED
        self.error_message = error_message
        self.delay = delay
        self.num_results = num_results
        self.request_count = 0
        self.last_request: SearchRequest | None = None

    @property
    def name(self) -> str:
        return self._name

    def _make_results(self, query: str) -> list[SearchResult]:
        return [
            SearchResult(
                title=f"{self._name} Result {i} for {query}",
                url=f"https://{self._name}.example.com/result/{i}",
                snippet=f"Snippet {i} from {self._name}",
                position=i,
                backend=self._name,
            )
            for i in range(self.num_results)
        ]

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.request_count += 1
        self.last_request = request

        if self.delay > 0:
            await asyncio.sleep(self.delay)

        # Check if we should fail
        should_fail = False
        if (
            self.behavior in ("always_fail", "raise_timeout", "raise_connection", "raise_dns", "raise_ssl")
            or self.behavior == "fail_n_times"
            and self.request_count <= self.fail_count
        ):
            should_fail = True

        if should_fail:
            if self.behavior in ("raise_timeout", "raise_connection", "raise_dns", "raise_ssl"):
                if self.behavior == "raise_timeout":
                    raise asyncio.TimeoutError(f"{self._name} request timed out")
                elif self.behavior == "raise_connection":
                    raise ConnectionError(f"{self._name} connection refused")
                elif self.behavior == "raise_dns":
                    raise OSError(f"[Errno -2] Name or service not known: {self._name}.example.com")
                elif self.behavior == "raise_ssl":
                    raise SSLSimulationError(f"SSL certificate verify failed for {self._name}")

            response = SearchResponse.error(
                query=request.query,
                provider=self._name,
                error_type=self.error_code,
                error_message=self.error_message,
                retryable=True,
            )
            self._update_health_from_response(response)
            return response

        results = self._make_results(request.query)
        response = SearchResponse.success(
            query=request.query,
            provider=self._name,
            results=results,
        )
        self._update_health_from_response(response)
        return response

    async def health(self):
        return self.get_health()


class SSLSimulationError(Exception):
    """Simulated SSL error."""


# ============================================================
# System-level Search Orchestrator (for testing)
# ============================================================


@dataclass
class OrchestratorConfig:
    """Configuration for the search orchestrator."""

    max_retries: int = 2
    circuit_failure_threshold: int = 3
    circuit_recovery_time: int = 60  # seconds, same as BackendHealth default
    request_timeout: float = 5.0


class SearchOrchestrator:
    """System-level search orchestrator with fallback and circuit breaking.

    This is a simplified version of what the production SearchService will be.
    It manages multiple SearchProviders and implements:
      - Sequential fallback (try provider 1, if fails try provider 2, etc.)
      - Circuit breaker per provider
      - Health tracking
    """

    def __init__(
        self,
        providers: list[SearchProvider],
        config: OrchestratorConfig | None = None,
    ):
        self.providers = providers
        self.config = config or OrchestratorConfig()
        self.health_manager = SearchHealthManager(
            backend_names=[p.name for p in providers],
            failure_threshold=self.config.circuit_failure_threshold,
            recovery_time=self.config.circuit_recovery_time,
        )
        self.total_requests = 0
        self.fallback_count = 0
        self.last_used_provider: str | None = None

    def _is_provider_available(self, name: str) -> bool:
        backend = self.health_manager.get_backend(name)
        return backend is not None and backend.can_use()

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute search with fallback and circuit breaking."""
        self.total_requests += 1
        errors: list[SearchResponse] = []

        for provider in self.providers:
            if not self._is_provider_available(provider.name):
                errors.append(
                    SearchResponse.error(
                        query=request.query,
                        provider=provider.name,
                        error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                        error_message=f"Circuit open for {provider.name}",
                        retryable=False,
                    )
                )
                continue

            try:
                response = await asyncio.wait_for(
                    provider.search(request),
                    timeout=self.config.request_timeout,
                )

                if response.is_success:
                    self.health_manager.record_success(provider.name)
                    self.last_used_provider = provider.name
                    if len(errors) > 0:
                        self.fallback_count += 1
                    return response
                else:
                    self.health_manager.record_failure(
                        provider.name,
                        response.error_message or "Unknown error",
                    )
                    errors.append(response)

            except asyncio.TimeoutError:
                self.health_manager.record_failure(provider.name, "Timeout")
                errors.append(
                    SearchResponse.error(
                        query=request.query,
                        provider=provider.name,
                        error_type=StandardErrorCode.FETCH_TIMEOUT,
                        error_message=f"Timeout for {provider.name}",
                        retryable=True,
                    )
                )
            except Exception as e:
                self.health_manager.record_failure(provider.name, str(e))
                errors.append(
                    SearchResponse.error(
                        query=request.query,
                        provider=provider.name,
                        error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                        error_message=f"{type(e).__name__}: {e}",
                        retryable=True,
                    )
                )

        return SearchResponse.error(
            query=request.query,
            provider="all",
            error_type=StandardErrorCode.SEARCH_ALL_BACKENDS_FAILED,
            error_message=f"All {len(self.providers)} providers failed",
            retryable=True,
        )

    def get_health_report(self) -> dict[str, Any]:
        return self.health_manager.get_health_report()

    def get_backend_health(self, name: str) -> dict[str, Any] | None:
        backend = self.health_manager.get_backend(name)
        return backend.to_dict() if backend else None

    async def close(self):
        for provider in self.providers:
            await provider.close()


# ============================================================
# System-level fault injection tests
# ============================================================


class TestSystemLevelFallback:
    """Test that the system correctly falls back when a provider fails."""

    @pytest.mark.asyncio
    async def test_first_provider_429_fallback_to_second(self):
        """Provider 1 returns 429, system falls back to Provider 2."""
        provider1 = FakeSearchProvider(
            "bing",
            behavior="always_fail",
            error_code=StandardErrorCode.FETCH_RATE_LIMITED,
            error_message="429 Too Many Requests",
        )
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator([provider1, provider2])
        request = SearchRequest(query="test query")

        response = await orchestrator.search(request)

        assert response.is_success
        assert response.provider == "duckduckgo"
        assert orchestrator.fallback_count == 1
        assert provider1.request_count == 1
        assert provider2.request_count == 1
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_provider_timeout_fallback(self):
        """Provider 1 times out, system falls back to Provider 2."""
        provider1 = FakeSearchProvider("bing", behavior="raise_timeout")
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator(
            [provider1, provider2],
            config=OrchestratorConfig(request_timeout=0.1),
        )
        request = SearchRequest(query="test query")

        response = await orchestrator.search(request)

        assert response.is_success
        assert response.provider == "duckduckgo"
        assert orchestrator.fallback_count == 1
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_dns_failure_fallback(self):
        """Provider 1 has DNS failure, system falls back to Provider 2."""
        provider1 = FakeSearchProvider("bing", behavior="raise_dns")
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator([provider1, provider2])
        request = SearchRequest(query="test query")

        response = await orchestrator.search(request)

        assert response.is_success
        assert response.provider == "duckduckgo"
        assert orchestrator.fallback_count == 1
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_ssl_failure_fallback(self):
        """Provider 1 has SSL error, system falls back to Provider 2."""
        provider1 = FakeSearchProvider("bing", behavior="raise_ssl")
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator([provider1, provider2])
        request = SearchRequest(query="test query")

        response = await orchestrator.search(request)

        assert response.is_success
        assert response.provider == "duckduckgo"
        assert orchestrator.fallback_count == 1
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_fail_n_times_then_succeed(self):
        """Provider fails N times then succeeds."""
        provider1 = FakeSearchProvider("bing", behavior="fail_n_times", fail_count=2)
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator([provider1, provider2])
        request = SearchRequest(query="test query")

        for i in range(2):
            response = await orchestrator.search(request)
            assert response.is_success
            assert response.provider == "duckduckgo"

        response = await orchestrator.search(request)
        assert response.is_success
        assert response.provider == "bing"
        assert provider1.request_count == 3
        await orchestrator.close()


class TestSystemLevelCircuitBreaker:
    """Test circuit breaker behavior at the system level."""

    @pytest.mark.asyncio
    async def test_circuit_opens_after_repeated_failures(self):
        """Repeated failures open the circuit, provider is skipped."""
        provider1 = FakeSearchProvider("bing", behavior="always_fail")
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator(
            [provider1, provider2],
            config=OrchestratorConfig(circuit_failure_threshold=3),
        )
        request = SearchRequest(query="test query")

        for i in range(3):
            response = await orchestrator.search(request)
            assert response.is_success
            assert response.provider == "duckduckgo"
            assert provider1.request_count == i + 1

        # 4th request: circuit should be open, provider1 is NOT tried
        response = await orchestrator.search(request)
        assert response.is_success
        assert response.provider == "duckduckgo"
        assert provider1.request_count == 3  # Still 3, not 4!

        backend = orchestrator.get_backend_health("bing")
        assert backend is not None
        assert backend["circuit_open"] is True
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_circuit_recovers_after_timeout(self):
        """Circuit opens, then recovers after reset timeout."""
        provider1 = FakeSearchProvider("bing", behavior="fail_n_times", fail_count=3)
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator(
            [provider1, provider2],
            config=OrchestratorConfig(
                circuit_failure_threshold=3,
                circuit_recovery_time=1,
            ),
        )
        request = SearchRequest(query="test query")

        for i in range(3):
            response = await orchestrator.search(request)
            assert response.provider == "duckduckgo"

        backend = orchestrator.get_backend_health("bing")
        assert backend is not None
        assert backend["circuit_open"] is True

        # Wait for recovery
        await asyncio.sleep(1.2)

        # Next request: circuit should be half-open, provider1 is tried
        response = await orchestrator.search(request)
        assert response.provider == "bing"  # provider1 succeeded!
        assert provider1.request_count == 4

        backend = orchestrator.get_backend_health("bing")
        assert backend is not None
        assert backend["circuit_open"] is False
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_circuit_half_open_failure_reopens(self):
        """Half-open request fails, circuit reopens."""
        provider1 = FakeSearchProvider("bing", behavior="always_fail")
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator(
            [provider1, provider2],
            config=OrchestratorConfig(
                circuit_failure_threshold=2,
                circuit_recovery_time=1,
            ),
        )
        request = SearchRequest(query="test query")

        for i in range(2):
            await orchestrator.search(request)

        assert provider1.request_count == 2

        await asyncio.sleep(1.2)

        # Half-open request: provider1 is tried, fails again
        response = await orchestrator.search(request)
        assert response.provider == "duckduckgo"
        assert provider1.request_count == 3

        backend = orchestrator.get_backend_health("bing")
        assert backend is not None
        assert backend["circuit_open"] is True

        # Next request: circuit is open, provider1 NOT tried
        response = await orchestrator.search(request)
        assert provider1.request_count == 3
        await orchestrator.close()


class TestSystemLevelAllFailures:
    """Test behavior when all providers fail."""

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_standard_error(self):
        """All providers fail, returns standardized error."""
        provider1 = FakeSearchProvider("bing", behavior="always_fail")
        provider2 = FakeSearchProvider("duckduckgo", behavior="always_fail")
        provider3 = FakeSearchProvider("serpapi", behavior="always_fail")

        orchestrator = SearchOrchestrator([provider1, provider2, provider3])
        request = SearchRequest(query="test query")

        response = await orchestrator.search(request)

        assert response.is_error
        assert response.error_type == StandardErrorCode.SEARCH_ALL_BACKENDS_FAILED
        assert response.provider == "all"
        assert response.retryable is True
        assert "All 3 providers failed" in (response.error_message or "")
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_all_circuits_open_skips_all_providers(self):
        """All circuits open, no providers are tried."""
        provider1 = FakeSearchProvider("bing", behavior="always_fail")
        provider2 = FakeSearchProvider("duckduckgo", behavior="always_fail")

        orchestrator = SearchOrchestrator(
            [provider1, provider2],
            config=OrchestratorConfig(circuit_failure_threshold=2),
        )
        request = SearchRequest(query="test query")

        for i in range(2):
            await orchestrator.search(request)

        assert provider1.request_count == 2
        assert provider2.request_count == 2

        # 3rd request: both circuits open, neither is tried
        response = await orchestrator.search(request)
        assert response.is_error
        assert provider1.request_count == 2
        assert provider2.request_count == 2
        await orchestrator.close()


class TestSystemLevelHealthTracking:
    """Test that health is correctly tracked at the system level."""

    @pytest.mark.asyncio
    async def test_health_report_shows_failure_count(self):
        """Health report accurately tracks failures."""
        provider1 = FakeSearchProvider("bing", behavior="always_fail")
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator(
            [provider1, provider2],
            config=OrchestratorConfig(circuit_failure_threshold=10),
        )
        request = SearchRequest(query="test query")

        for i in range(5):
            await orchestrator.search(request)

        bing = orchestrator.get_backend_health("bing")
        ddg = orchestrator.get_backend_health("duckduckgo")
        assert bing is not None
        assert ddg is not None
        assert bing["total_failures"] == 5
        assert ddg["total_failures"] == 0
        assert ddg["total_successes"] == 5
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_success_resets_failure_streak(self):
        """A success resets the failure streak."""
        provider1 = FakeSearchProvider("bing", behavior="fail_n_times", fail_count=2)
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator(
            [provider1, provider2],
            config=OrchestratorConfig(circuit_failure_threshold=3),
        )
        request = SearchRequest(query="test query")

        for i in range(2):
            await orchestrator.search(request)

        response = await orchestrator.search(request)
        assert response.provider == "bing"

        bing = orchestrator.get_backend_health("bing")
        assert bing is not None
        assert bing["consecutive_failures"] == 0
        assert bing["total_successes"] == 1
        await orchestrator.close()


class TestSystemLevelProviderIsolation:
    """Test that failures in one provider don't affect others."""

    @pytest.mark.asyncio
    async def test_one_provider_failure_doesnt_affect_others(self):
        """Provider 1 failing doesn't affect Provider 2's health."""
        provider1 = FakeSearchProvider("bing", behavior="always_fail")
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")
        provider3 = FakeSearchProvider("serpapi", behavior="success")

        orchestrator = SearchOrchestrator(
            [provider1, provider2, provider3],
            config=OrchestratorConfig(circuit_failure_threshold=20),
        )
        request = SearchRequest(query="test query")

        for i in range(10):
            await orchestrator.search(request)

        bing = orchestrator.get_backend_health("bing")
        ddg = orchestrator.get_backend_health("duckduckgo")
        serpapi = orchestrator.get_backend_health("serpapi")
        assert bing is not None and ddg is not None and serpapi is not None
        assert bing["total_failures"] == 10
        assert ddg["total_successes"] == 10
        assert serpapi["total_successes"] == 0  # Never tried
        assert serpapi["total_failures"] == 0
        await orchestrator.close()

    @pytest.mark.asyncio
    async def test_failed_provider_recovery_doesnt_affect_others(self):
        """When a failed provider recovers, others remain healthy."""
        provider1 = FakeSearchProvider("bing", behavior="fail_n_times", fail_count=3)
        provider2 = FakeSearchProvider("duckduckgo", behavior="success")

        orchestrator = SearchOrchestrator(
            [provider1, provider2],
            config=OrchestratorConfig(circuit_failure_threshold=10),
        )
        request = SearchRequest(query="test query")

        for i in range(3):
            await orchestrator.search(request)

        response = await orchestrator.search(request)
        assert response.provider == "bing"

        bing = orchestrator.get_backend_health("bing")
        ddg = orchestrator.get_backend_health("duckduckgo")
        assert bing is not None and ddg is not None
        assert bing["consecutive_failures"] == 0
        assert ddg["consecutive_failures"] == 0
        await orchestrator.close()
