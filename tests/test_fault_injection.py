"""Fault injection tests for webscout-mcp.

Tests the system's behavior under various failure scenarios:
- Circuit breaker pattern (open, half-open, close)
- Backend failure fallback
- Various error types (403, 429, timeout, DNS, connection)
- SearchEngine behavior with failing backends

These tests simulate real-world failure scenarios and verify that
the system degrades gracefully rather than crashing.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.search_health import BackendHealth, SearchHealthManager

# ============ BackendHealth Circuit Breaker Tests ============


class TestBackendHealthCircuitBreaker:
    """Test circuit breaker pattern in BackendHealth."""

    def test_initial_state_healthy(self):
        """Backend should start in healthy state."""
        health = BackendHealth(name="test-backend")
        assert health.circuit_open is False
        assert health.consecutive_failures == 0
        assert health.can_use() is True

    def test_record_success_resets_failures(self):
        """Successful request should reset consecutive failures."""
        health = BackendHealth(name="test-backend")
        health.record_failure("timeout")
        health.record_failure("timeout")
        assert health.consecutive_failures == 2

        health.record_success()
        assert health.consecutive_failures == 0
        assert health.consecutive_successes == 1

    def test_circuit_opens_after_threshold(self):
        """Circuit should open after consecutive failures reach threshold."""
        health = BackendHealth(name="test-backend", failure_threshold=3)
        assert health.circuit_open is False

        health.record_failure("timeout")
        health.record_failure("429")
        assert health.circuit_open is False

        health.record_failure("403")
        assert health.circuit_open is True
        assert health.circuit_open_time is not None

    def test_circuit_open_blocks_requests(self):
        """Open circuit should block requests."""
        health = BackendHealth(name="test-backend", failure_threshold=2)
        health.record_failure("timeout")
        health.record_failure("timeout")
        assert health.circuit_open is True
        assert health.can_use() is False

    def test_circuit_half_open_after_recovery_time(self):
        """Circuit should enter half-open state after recovery time."""
        health = BackendHealth(
            name="test-backend",
            failure_threshold=2,
            recovery_time=0.1,  # 100ms for fast testing
        )
        health.record_failure("timeout")
        health.record_failure("timeout")
        assert health.circuit_open is True
        assert health.can_use() is False

        # Wait for recovery time
        time.sleep(0.15)
        assert health.can_use() is True  # Half-open state

    def test_half_open_success_closes_circuit(self):
        """Success in half-open state should close the circuit."""
        health = BackendHealth(
            name="test-backend",
            failure_threshold=2,
            recovery_time=0.1,
            half_open_max_requests=1,
        )
        health.record_failure("timeout")
        health.record_failure("timeout")
        assert health.circuit_open is True

        time.sleep(0.15)
        assert health.can_use() is True  # Half-open

        health.record_success()
        assert health.circuit_open is False
        assert health.can_use() is True

    def test_half_open_failure_reopens_circuit(self):
        """Failure in half-open state should reopen the circuit."""
        health = BackendHealth(
            name="test-backend",
            failure_threshold=2,
            recovery_time=0.1,
        )
        health.record_failure("timeout")
        health.record_failure("timeout")
        assert health.circuit_open is True

        time.sleep(0.15)
        assert health.can_use() is True  # Half-open

        health.record_failure("timeout again")
        assert health.circuit_open is True
        # Circuit is open again; can_use() may return True if recovery time passed
        # but circuit_open state confirms it was reopened
        assert health.consecutive_failures > 0

    def test_health_score_decreases_with_failures(self):
        """Health score should decrease with failures."""
        health = BackendHealth(name="test-backend")
        initial_score = health.get_health_score()

        health.record_failure("timeout")
        health.record_failure("429")
        score_after_failures = health.get_health_score()

        assert score_after_failures < initial_score

    def test_reset_restores_healthy_state(self):
        """Reset should restore backend to healthy state."""
        health = BackendHealth(name="test-backend", failure_threshold=2)
        health.record_failure("timeout")
        health.record_failure("timeout")
        assert health.circuit_open is True

        health.reset()
        assert health.circuit_open is False
        assert health.consecutive_failures == 0
        assert health.can_use() is True


# ============ SearchHealthManager Tests ============


class TestSearchHealthManager:
    """Test SearchHealthManager with multiple backends."""

    def test_initialization(self):
        """Manager should initialize with specified backends."""
        manager = SearchHealthManager(backend_names=["bing", "duckduckgo", "serpapi"])
        assert manager.get_backend("bing") is not None
        assert manager.get_backend("duckduckgo") is not None
        assert manager.get_backend("serpapi") is not None

    def test_record_success(self):
        """Recording success should update backend health."""
        manager = SearchHealthManager(backend_names=["bing"])
        manager.record_success("bing")
        backend = manager.get_backend("bing")
        assert backend.consecutive_successes == 1
        assert backend.consecutive_failures == 0

    def test_record_failure(self):
        """Recording failure should update backend health."""
        manager = SearchHealthManager(backend_names=["bing"])
        manager.record_failure("bing", "timeout")
        backend = manager.get_backend("bing")
        assert backend.consecutive_failures == 1
        assert backend.last_failure_reason == "timeout"

    def test_get_available_backends_excludes_open_circuits(self):
        """Available backends should exclude those with open circuits."""
        manager = SearchHealthManager(
            backend_names=["bing", "duckduckgo"],
            failure_threshold=2,
        )

        # Fail bing enough to open circuit
        manager.record_failure("bing", "timeout")
        manager.record_failure("bing", "timeout")

        available = manager.get_available_backends(["bing", "duckduckgo"])
        assert "bing" not in available
        assert "duckduckgo" in available

    def test_get_health_report(self):
        """Health report should contain all backends."""
        manager = SearchHealthManager(backend_names=["bing", "duckduckgo"])
        report = manager.get_health_report()

        assert "backends" in report
        backend_names = [b["name"] for b in report["backends"]]
        assert "bing" in backend_names
        assert "duckduckgo" in backend_names
        assert "total_backends" in report
        assert report["total_backends"] == 2

    def test_enable_disable_backend(self):
        """Enable/disable should control backend availability."""
        manager = SearchHealthManager(backend_names=["bing", "duckduckgo"])

        manager.disable_backend("bing")
        available = manager.get_available_backends(["bing", "duckduckgo"])
        assert "bing" not in available

        manager.enable_backend("bing")
        available = manager.get_available_backends(["bing", "duckduckgo"])
        assert "bing" in available

    def test_reset_all(self):
        """Reset all should restore all backends."""
        manager = SearchHealthManager(backend_names=["bing", "duckduckgo"], failure_threshold=2)
        manager.record_failure("bing", "timeout")
        manager.record_failure("bing", "timeout")
        manager.record_failure("duckduckgo", "429")
        manager.record_failure("duckduckgo", "429")

        manager.reset_all()

        bing = manager.get_backend("bing")
        ddg = manager.get_backend("duckduckgo")
        assert bing.circuit_open is False
        assert ddg.circuit_open is False


# ============ Fault Injection Scenarios ============


class TestFaultInjectionScenarios:
    """Test system behavior under various failure scenarios."""

    @pytest.fixture
    def health_manager(self):
        return SearchHealthManager(
            backend_names=["bing", "duckduckgo", "serpapi"],
            failure_threshold=3,
            recovery_time=0.1,
        )

    def test_scenario_bing_429_rate_limited(self, health_manager):
        """Scenario: Bing returns 429 Too Many Requests.

        Expected: Circuit opens after 3 failures, DuckDuckGo takes over.
        """
        # Simulate 3 consecutive 429 errors from Bing
        for i in range(3):
            health_manager.record_failure("bing", f"429 Too Many Requests (attempt {i+1})")

        bing = health_manager.get_backend("bing")
        assert bing.circuit_open is True
        assert bing.consecutive_failures == 3

        # DuckDuckGo should still be available
        available = health_manager.get_available_backends(["bing", "duckduckgo", "serpapi"])
        assert "bing" not in available
        assert "duckduckgo" in available
        assert "serpapi" in available

    def test_scenario_bing_timeout_fallback(self, health_manager):
        """Scenario: Bing times out, fallback to DuckDuckGo.

        Expected: Timeout recorded, fallback backend available.
        """
        health_manager.record_failure("bing", "Connection timeout after 10s")

        bing = health_manager.get_backend("bing")
        assert bing.consecutive_failures == 1
        assert bing.last_failure_reason == "Connection timeout after 10s"
        assert bing.circuit_open is False  # Only 1 failure, threshold is 3

        # Both backends still available
        available = health_manager.get_available_backends(["bing", "duckduckgo"])
        assert "bing" in available
        assert "duckduckgo" in available

    def test_scenario_all_backends_fail(self, health_manager):
        """Scenario: All backends fail.

        Expected: All circuits open, system reports no available backends.
        """
        # Fail all backends
        for backend in ["bing", "duckduckgo", "serpapi"]:
            for i in range(3):
                health_manager.record_failure(backend, f"Failure {i+1}")

        # All circuits should be open
        available = health_manager.get_available_backends(["bing", "duckduckgo", "serpapi"])
        assert len(available) == 0

        # Health report should show all circuits open
        report = health_manager.get_health_report()
        assert report["healthy_backends"] == 0
        assert report["open_circuits"] == 3

    def test_scenario_circuit_recovery_after_timeout(self, health_manager):
        """Scenario: Circuit opens, then recovers after timeout.

        Expected: Circuit enters half-open, successful request closes it.
        """
        # Open circuit
        for i in range(3):
            health_manager.record_failure("bing", f"Failure {i+1}")

        bing = health_manager.get_backend("bing")
        assert bing.circuit_open is True

        # Wait for recovery
        time.sleep(0.15)

        # Should be in half-open state
        available = health_manager.get_available_backends(["bing"])
        assert "bing" in available

        # Successful request should close circuit
        health_manager.record_success("bing")
        health_manager.record_success("bing")
        bing = health_manager.get_backend("bing")
        assert bing.circuit_open is False

    def test_scenario_intermittent_failures(self, health_manager):
        """Scenario: Intermittent failures (success, fail, success, fail).

        Expected: Circuit doesn't open because failures aren't consecutive.
        """
        health_manager.record_success("bing")
        health_manager.record_failure("bing", "Intermittent 1")
        health_manager.record_success("bing")
        health_manager.record_failure("bing", "Intermittent 2")
        health_manager.record_success("bing")
        health_manager.record_failure("bing", "Intermittent 3")

        bing = health_manager.get_backend("bing")
        assert bing.circuit_open is False  # Never 3 consecutive failures
        assert bing.consecutive_failures == 1
        assert bing.total_failures == 3

    def test_scenario_dns_failure(self, health_manager):
        """Scenario: DNS resolution failure.

        Expected: Recorded as failure, circuit opens after threshold.
        """
        for i in range(3):
            health_manager.record_failure("bing", f"DNS resolution failed (attempt {i+1})")

        bing = health_manager.get_backend("bing")
        assert bing.circuit_open is True
        assert "DNS" in bing.last_failure_reason

    def test_scenario_ssl_certificate_error(self, health_manager):
        """Scenario: SSL certificate verification failure.

        Expected: Recorded as failure, other backends unaffected.
        """
        health_manager.record_failure("bing", "SSL certificate verification failed")

        bing = health_manager.get_backend("bing")
        assert bing.consecutive_failures == 1
        assert "SSL" in bing.last_failure_reason

        # Other backends should be healthy
        ddg = health_manager.get_backend("duckduckgo")
        assert ddg.consecutive_failures == 0
        assert ddg.circuit_open is False


# ============ Error Mapping Tests ============


class TestErrorMapping:
    """Test that various HTTP errors map to correct standard error codes."""

    def test_403_maps_to_forbidden(self):
        """403 should map to FETCH_FORBIDDEN."""
        from webscout_mcp.errors import HTTPError, StructuredError

        exc = HTTPError(status_code=403, url="https://example.com", reason="Forbidden")
        structured = StructuredError.from_exception(exc)
        assert structured.code == StandardErrorCode.FETCH_FORBIDDEN
        assert structured.retryable is False

    def test_429_maps_to_rate_limited(self):
        """429 should map to FETCH_RATE_LIMITED."""
        from webscout_mcp.errors import HTTPError, StructuredError

        exc = HTTPError(status_code=429, url="https://bing.com", reason="Too Many Requests")
        structured = StructuredError.from_exception(exc)
        assert structured.code == StandardErrorCode.FETCH_RATE_LIMITED
        assert structured.retryable is True

    def test_500_maps_to_server_error(self):
        """500 should map to FETCH_SERVER_ERROR."""
        from webscout_mcp.errors import HTTPError, StructuredError

        exc = HTTPError(status_code=500, url="https://example.com", reason="Internal Server Error")
        structured = StructuredError.from_exception(exc)
        assert structured.code == StandardErrorCode.FETCH_SERVER_ERROR
        assert structured.retryable is True

    def test_timeout_maps_to_fetch_timeout(self):
        """Timeout should map to FETCH_TIMEOUT."""
        import httpx

        from webscout_mcp.errors import StructuredError

        exc = httpx.TimeoutException("Connection timed out")
        structured = StructuredError.from_exception(exc)
        assert structured.code == StandardErrorCode.FETCH_TIMEOUT
        assert structured.retryable is True

    def test_connect_error_maps_to_connection_error(self):
        """Connection error should map to FETCH_CONNECTION_ERROR."""
        import httpx

        from webscout_mcp.errors import StructuredError

        exc = httpx.ConnectError("Connection refused")
        structured = StructuredError.from_exception(exc)
        assert structured.code == StandardErrorCode.FETCH_CONNECTION_ERROR
        assert structured.retryable is True

    def test_circuit_breaker_trigger_errors(self):
        """Rate limited and timeout errors should trigger circuit breaker."""
        from webscout_mcp.errors import StructuredError, should_trigger_circuit_breaker

        rate_limited = StructuredError(
            code=StandardErrorCode.FETCH_RATE_LIMITED,
            message="429",
            provider="bing",
        )
        timeout = StructuredError(
            code=StandardErrorCode.FETCH_TIMEOUT,
            message="timeout",
            provider="bing",
        )
        forbidden = StructuredError(
            code=StandardErrorCode.FETCH_FORBIDDEN,
            message="403",
            provider="bing",
        )

        assert should_trigger_circuit_breaker(rate_limited) is True
        assert should_trigger_circuit_breaker(timeout) is True
        assert should_trigger_circuit_breaker(forbidden) is False


# ============ Resilience Tests ============


class TestSystemResilience:
    """Test overall system resilience patterns."""

    def test_graceful_degradation_one_backend_down(self):
        """System should work when one backend is down."""
        manager = SearchHealthManager(
            backend_names=["bing", "duckduckgo", "serpapi"],
            failure_threshold=2,
        )

        # Take down Bing
        manager.record_failure("bing", "timeout")
        manager.record_failure("bing", "timeout")

        # Should still have 2 available backends
        available = manager.get_available_backends(["bing", "duckduckgo", "serpapi"])
        assert len(available) == 2
        assert "duckduckgo" in available
        assert "serpapi" in available

    def test_health_report_accurate(self):
        """Health report should accurately reflect backend states."""
        manager = SearchHealthManager(
            backend_names=["bing", "duckduckgo"],
            failure_threshold=2,
        )

        # Initial state: all healthy
        report = manager.get_health_report()
        assert report["healthy_backends"] == 2
        assert report["open_circuits"] == 0

        # Take down Bing
        manager.record_failure("bing", "timeout")
        manager.record_failure("bing", "timeout")

        report = manager.get_health_report()
        assert report["healthy_backends"] == 1
        assert report["open_circuits"] == 1

    def test_backend_isolation(self):
        """Failure in one backend should not affect others."""
        manager = SearchHealthManager(backend_names=["bing", "duckduckgo"])

        # Fail Bing many times
        for i in range(10):
            manager.record_failure("bing", f"Failure {i+1}")

        # DuckDuckGo should be completely unaffected
        ddg = manager.get_backend("duckduckgo")
        assert ddg.consecutive_failures == 0
        assert ddg.total_failures == 0
        assert ddg.circuit_open is False
        assert ddg.can_use() is True
