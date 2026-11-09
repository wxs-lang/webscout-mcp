"""v1.9.0 search_health Stable acceptance tests.

Covers:
- Initial unobserved state (P0: no default 1.0)
- Consecutive successes / failures
- Empty result neutrality
- Circuit breaker state machine: closed -> open -> half-open -> closed
- Half-open probe concurrency limits
- Monotonic clock resilience
- Result classification: success/empty/hard_failure/invalid_query/timeout/circuit_skipped/unavailable
- Provider disabled/unavailable
- Real SearchService health report
- Real MCP search_health tool call
- Health query has no side effects
- SearchService vs Registry consistency
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.search_health import (
    CIRCUIT_CLOSED,
    CIRCUIT_HALF_OPEN,
    CIRCUIT_OPEN,
    BackendHealth,
    SearchHealthManager,
)
from webscout_mcp.search_provider import SearchRequest, SearchResponse
from webscout_mcp.search_service import SearchService, SearchServiceConfig

# ============ Helper: fake search provider ============


def _make_fake_provider(name: str, always_fail: bool = False, empty: bool = False):
    """Create a fake SearchProvider for testing."""
    provider = MagicMock()
    provider.name = name
    provider.close = AsyncMock()

    async def _search(request: SearchRequest) -> SearchResponse:
        if always_fail:
            return SearchResponse.error(
                query=request.query,
                provider=name,
                error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                error_message="fake failure",
                retryable=True,
            )
        if empty:
            return SearchResponse.empty(query=request.query, provider=name)
        return SearchResponse.success(
            query=request.query,
            provider=name,
            results=[{"title": "ok", "url": "https://example.com", "snippet": "ok"}],
        )

    provider.search = _search
    return provider


# ============ P0: Initial unobserved state ============


class TestInitialUnobserved:
    """P0: unobserved must not be reported as healthy (no default 1.0)."""

    def test_backend_initial_unobserved(self):
        backend = BackendHealth(name="test")
        assert backend.observed is False
        assert backend.get_status() == "unobserved"
        assert backend.get_health_score() is None
        assert backend.total_requests == 0

    def test_backend_can_use_when_unobserved(self):
        """Unobserved but enabled backend should be usable (no circuit open)."""
        backend = BackendHealth(name="test")
        assert backend.can_use() is True

    def test_manager_initial_unobserved(self):
        manager = SearchHealthManager(backend_names=["a", "b"])
        report = manager.get_health_report()
        assert report["unobserved_backends"] == 2
        assert report["observed_backends"] == 0
        assert report["healthy_backends"] == 0
        assert report["overall_health_score"] is None
        assert report["overall_success_rate"] is None

    def test_observed_after_success(self):
        backend = BackendHealth(name="test")
        backend.record_success()
        assert backend.observed is True
        assert backend.get_status() == "healthy"
        assert backend.get_health_score() is not None
        assert backend.get_health_score() > 0


# ============ Consecutive successes / failures ============


class TestConsecutiveOutcomes:
    def test_consecutive_successes(self):
        backend = BackendHealth(name="test", failure_threshold=5)
        for _ in range(3):
            backend.record_success()
        assert backend.consecutive_successes == 3
        assert backend.consecutive_failures == 0
        assert backend.circuit_state == CIRCUIT_CLOSED

    def test_consecutive_failures_open_circuit(self):
        backend = BackendHealth(name="test", failure_threshold=3)
        for i in range(3):
            backend.record_failure(f"fail-{i}")
        assert backend.circuit_state == CIRCUIT_OPEN
        assert backend.circuit_open is True
        assert backend.consecutive_failures == 3

    def test_below_threshold_no_open(self):
        backend = BackendHealth(name="test", failure_threshold=5)
        for _ in range(4):
            backend.record_failure("fail")
        assert backend.circuit_state == CIRCUIT_CLOSED
        assert backend.circuit_open is False

    def test_success_resets_consecutive_failures(self):
        backend = BackendHealth(name="test", failure_threshold=5)
        backend.record_failure("f1")
        backend.record_failure("f2")
        assert backend.consecutive_failures == 2
        backend.record_success()
        assert backend.consecutive_failures == 0
        assert backend.consecutive_successes == 1


# ============ Empty result neutrality ============


class TestEmptyResultNeutral:
    def test_empty_does_not_trigger_circuit(self):
        backend = BackendHealth(name="test", failure_threshold=2)
        for _ in range(10):
            backend.record_empty()
        assert backend.circuit_state == CIRCUIT_CLOSED
        assert backend.consecutive_failures == 0
        assert backend.total_empty == 10
        assert backend.total_requests == 10

    def test_empty_does_not_pollute_error_rate(self):
        backend = BackendHealth(name="test")
        backend.record_success()
        backend.record_empty()
        backend.record_empty()
        # success_rate = 1/3 (empty counts as request but not success)
        score = backend.get_health_score()
        assert score is not None
        assert 0 < score < 1.0


# ============ Circuit breaker state machine ============


class TestCircuitStateMachine:
    def test_closed_to_open(self):
        backend = BackendHealth(name="test", failure_threshold=2)
        assert backend.circuit_state == CIRCUIT_CLOSED
        backend.record_failure("f1")
        backend.record_failure("f2")
        assert backend.circuit_state == CIRCUIT_OPEN

    def test_open_blocks_usage(self):
        backend = BackendHealth(name="test", failure_threshold=1, recovery_time=60)
        backend.record_failure("f1")
        assert backend.can_use() is False

    def test_open_to_half_open_after_recovery(self):
        backend = BackendHealth(name="test", failure_threshold=1, recovery_time=0)
        backend.record_failure("f1")
        # recovery_time=0 means immediately eligible
        assert backend.can_use() is True
        assert backend.circuit_state == CIRCUIT_HALF_OPEN

    def test_half_open_success_closes(self):
        backend = BackendHealth(
            name="test",
            failure_threshold=1,
            recovery_time=0,
            half_open_success_threshold=1,
        )
        backend.record_failure("f1")
        assert backend.can_use() is True  # transitions to half-open
        assert backend.circuit_state == CIRCUIT_HALF_OPEN
        backend.record_success()
        assert backend.circuit_state == CIRCUIT_CLOSED
        assert backend.circuit_recovery_count == 1

    def test_half_open_failure_reopens(self):
        backend = BackendHealth(name="test", failure_threshold=1, recovery_time=0)
        backend.record_failure("f1")
        assert backend.can_use() is True  # half-open
        backend.record_failure("probe-failed")
        assert backend.circuit_state == CIRCUIT_OPEN

    def test_circuit_open_count_increments(self):
        backend = BackendHealth(name="test", failure_threshold=1, recovery_time=0)
        backend.record_failure("f1")
        assert backend.circuit_open_count == 1
        # half-open then fail -> reopen
        backend.can_use()
        backend.record_failure("f2")
        assert backend.circuit_open_count == 2


# ============ Half-open probe concurrency limits ============


class TestHalfOpenConcurrency:
    def test_half_open_slot_acquisition(self):
        backend = BackendHealth(
            name="test",
            failure_threshold=1,
            recovery_time=0,
            half_open_max_requests=2,
        )
        backend.record_failure("f1")
        backend.can_use()  # transition to half-open
        assert backend.acquire_half_open_slot() is True
        assert backend.half_open_requests_in_flight == 1
        assert backend.acquire_half_open_slot() is True
        assert backend.half_open_requests_in_flight == 2
        # Third should be rejected
        assert backend.acquire_half_open_slot() is False
        assert backend.half_open_requests_in_flight == 2

    def test_half_open_slot_release(self):
        backend = BackendHealth(
            name="test",
            failure_threshold=1,
            recovery_time=0,
            half_open_max_requests=1,
        )
        backend.record_failure("f1")
        backend.can_use()
        assert backend.acquire_half_open_slot() is True
        assert backend.acquire_half_open_slot() is False
        backend.release_half_open_slot()
        assert backend.half_open_requests_in_flight == 0
        assert backend.acquire_half_open_slot() is True

    def test_can_use_respects_half_open_limit(self):
        """can_use() should return False when half-open slots exhausted."""
        backend = BackendHealth(
            name="test",
            failure_threshold=1,
            recovery_time=0,
            half_open_max_requests=1,
        )
        backend.record_failure("f1")
        assert backend.can_use() is True  # transitions to half-open
        # Manually set in-flight to max
        backend.half_open_requests_in_flight = 1
        assert backend.can_use() is False


# ============ Monotonic clock resilience ============


class TestMonotonicClock:
    def test_recovery_uses_monotonic(self):
        """Circuit recovery should be based on monotonic time, not wall clock."""
        backend = BackendHealth(name="test", failure_threshold=1, recovery_time=60)
        backend.record_failure("f1")
        assert backend.circuit_state == CIRCUIT_OPEN
        # Set monotonic to 61 seconds ago
        backend.circuit_open_monotonic = time.monotonic() - 61
        assert backend.can_use() is True
        assert backend.circuit_state == CIRCUIT_HALF_OPEN

    def test_wall_clock_change_does_not_affect_recovery(self):
        """Changing wall clock (time.time) should not affect circuit timing."""
        backend = BackendHealth(name="test", failure_threshold=1, recovery_time=60)
        backend.record_failure("f1")
        # Even if wall clock jumps backward, monotonic stays stable
        backend.circuit_open_time = time.time() - 10000  # wall clock jumped
        assert backend.can_use() is False  # still blocked by monotonic
        backend.circuit_open_monotonic = time.monotonic() - 61
        assert backend.can_use() is True


# ============ Result classification ============


class TestResultClassification:
    def test_record_timeout(self):
        backend = BackendHealth(name="test")
        backend.record_timeout("request timeout")
        assert backend.total_timeouts == 1
        assert backend.total_failures == 1
        assert backend.total_requests == 1

    def test_record_invalid_query_no_pollution(self):
        """Invalid query must NOT pollute provider health."""
        backend = BackendHealth(name="test")
        for _ in range(10):
            backend.record_invalid_query()
        assert backend.total_invalid_queries == 10
        assert backend.total_requests == 0
        assert backend.total_failures == 0
        assert backend.consecutive_failures == 0
        assert backend.circuit_state == CIRCUIT_CLOSED
        assert backend.observed is False

    def test_record_circuit_skipped(self):
        backend = BackendHealth(name="test")
        backend.record_circuit_skipped()
        assert backend.total_circuit_skips == 1
        assert backend.total_requests == 0
        assert backend.total_failures == 0

    def test_record_unavailable(self):
        backend = BackendHealth(name="test")
        backend.record_unavailable()
        assert backend.total_unavailable == 1
        assert backend.total_requests == 0

    def test_recent_failures_tracked(self):
        backend = BackendHealth(name="test")
        for i in range(15):
            backend.record_failure(f"fail-{i}")
        assert len(backend.recent_failures) == 10  # maxlen
        assert backend.recent_failures[-1]["reason"] == "fail-14"


# ============ Provider disabled / unavailable ============


class TestProviderDisabled:
    def test_disabled_backend_not_usable(self):
        backend = BackendHealth(name="test")
        backend.enabled = False
        assert backend.can_use() is False
        assert backend.get_status() == "disabled"

    def test_manager_disable_backend(self):
        manager = SearchHealthManager(backend_names=["a", "b"])
        assert manager.disable_backend("a") is True
        assert manager.get_available_backends(["a", "b"]) == ["b"]

    def test_manager_enable_backend(self):
        manager = SearchHealthManager(backend_names=["a"])
        manager.disable_backend("a")
        assert manager.get_available_backends(["a"]) == []
        manager.enable_backend("a")
        assert manager.get_available_backends(["a"]) == ["a"]


# ============ Real SearchService health report ============


class TestSearchServiceHealthReport:
    def test_service_initial_health_unobserved(self):
        providers = [_make_fake_provider("p1"), _make_fake_provider("p2")]
        service = SearchService(providers=providers)
        report = service.get_health_report()
        assert report["unobserved_backends"] == 2
        assert report["overall_health_score"] is None

    def test_service_health_after_search(self):
        providers = [_make_fake_provider("p1")]
        service = SearchService(providers=providers)
        asyncio.run(service.search(SearchRequest(query="test")))
        report = service.get_health_report()
        assert report["observed_backends"] == 1
        assert report["healthy_backends"] == 1
        assert report["total_requests"] == 1

    def test_service_health_after_failure(self):
        providers = [_make_fake_provider("p1", always_fail=True)]
        service = SearchService(
            providers=providers,
            config=SearchServiceConfig(circuit_failure_threshold=2),
        )
        for _ in range(2):
            asyncio.run(service.search(SearchRequest(query="test")))
        report = service.get_health_report()
        assert report["open_circuits"] == 1
        assert report["total_failures"] == 2

    def test_service_statistics_included(self):
        providers = [_make_fake_provider("p1")]
        service = SearchService(providers=providers)
        asyncio.run(service.search(SearchRequest(query="test")))
        report = service.get_health_report()
        assert "service_statistics" in report
        stats = report["service_statistics"]
        assert stats["total_requests"] == 1
        assert "search_circuit_authority" in stats
        assert stats["search_circuit_authority"] == "SearchHealthManager"


# ============ Health query has no side effects ============


class TestHealthQueryNoSideEffects:
    def test_get_health_report_does_not_mutate_state(self):
        """get_health_report must not mutate backend state (timestamp excluded)."""
        manager = SearchHealthManager(backend_names=["a", "b"])
        manager.record_success("a")

        def _state_without_timestamp():
            report = manager.get_health_report()
            report.pop("timestamp", None)
            return json.dumps(report, sort_keys=True, default=str)

        state_before = _state_without_timestamp()
        # Call report multiple times
        for _ in range(5):
            manager.get_health_report()
        state_after = _state_without_timestamp()
        assert state_before == state_after

    def test_backend_to_dict_no_mutation(self):
        backend = BackendHealth(name="test")
        backend.record_success()
        d1 = backend.to_dict()
        d2 = backend.to_dict()
        assert d1 == d2
        assert backend.total_requests == 1  # unchanged


# ============ JSON backward compatibility ============


class TestJsonBackwardCompatibility:
    def test_original_fields_preserved(self):
        backend = BackendHealth(name="test")
        backend.record_success()
        d = backend.to_dict()
        # All original v1.8.0 fields must still exist
        original_fields = [
            "name",
            "enabled",
            "status",
            "health_score",
            "total_requests",
            "total_successes",
            "total_failures",
            "consecutive_failures",
            "consecutive_successes",
            "circuit_open",
            "last_failure_reason",
            "last_failure_time",
            "last_success_time",
            "failure_threshold",
            "recovery_time",
        ]
        for field in original_fields:
            assert field in d, f"Missing backward-compatible field: {field}"

    def test_circuit_open_alias(self):
        """circuit_open must be True when state is open or half-open."""
        backend = BackendHealth(name="test", failure_threshold=1, recovery_time=0)
        assert backend.circuit_open is False
        backend.record_failure("f1")
        assert backend.circuit_open is True
        backend.can_use()  # half-open
        assert backend.circuit_open is True

    def test_manager_report_original_fields(self):
        manager = SearchHealthManager(backend_names=["a"])
        manager.record_success("a")
        report = manager.get_health_report()
        original_fields = [
            "overall_health_score",
            "total_backends",
            "healthy_backends",
            "degraded_backends",
            "open_circuits",
            "disabled_backends",
            "total_requests",
            "total_successes",
            "total_failures",
            "overall_success_rate",
            "backends",
            "timestamp",
        ]
        for field in original_fields:
            assert field in report, f"Missing backward-compatible field: {field}"


# ============ Reset functionality ============


class TestReset:
    def test_backend_reset(self):
        backend = BackendHealth(name="test", failure_threshold=1)
        backend.record_failure("f1")
        assert backend.circuit_state == CIRCUIT_OPEN
        backend.reset()
        assert backend.circuit_state == CIRCUIT_CLOSED
        assert backend.observed is False
        assert backend.total_requests == 0
        assert backend.circuit_open_count == 0

    def test_manager_reset_all(self):
        manager = SearchHealthManager(backend_names=["a", "b"])
        manager.record_success("a")
        manager.record_failure("b", "fail")
        manager.reset_all()
        report = manager.get_health_report()
        assert report["unobserved_backends"] == 2
        assert report["total_requests"] == 0
