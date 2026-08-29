"""Tests for search backend health management."""

import time
import pytest

from webscout_mcp.search_health import BackendHealth, SearchHealthManager


class TestBackendHealth:
    """Tests for BackendHealth class."""

    def test_initial_state(self):
        """Test initial health state."""
        backend = BackendHealth(name="test")
        assert backend.name == "test"
        assert backend.enabled is True
        assert backend.consecutive_failures == 0
        assert backend.consecutive_successes == 0
        assert backend.total_requests == 0
        assert backend.circuit_open is False
        assert backend.can_use() is True
        assert backend.get_status() == "healthy"
        assert backend.get_health_score() == 1.0

    def test_record_success(self):
        """Test recording successful requests."""
        backend = BackendHealth(name="test")
        backend.record_success()
        assert backend.total_requests == 1
        assert backend.total_successes == 1
        assert backend.consecutive_successes == 1
        assert backend.consecutive_failures == 0
        assert backend.last_success_time is not None

    def test_record_failure(self):
        """Test recording failed requests."""
        backend = BackendHealth(name="test")
        backend.record_failure("timeout")
        assert backend.total_requests == 1
        assert backend.total_failures == 1
        assert backend.consecutive_failures == 1
        assert backend.last_failure_reason == "timeout"
        assert backend.last_failure_time is not None

    def test_circuit_breaker_opens(self):
        """Test that circuit opens after threshold failures."""
        backend = BackendHealth(name="test", failure_threshold=3)
        assert backend.can_use() is True

        # Record failures up to threshold
        for i in range(3):
            backend.record_failure(f"failure {i}")

        assert backend.circuit_open is True
        assert backend.can_use() is False
        assert backend.get_status() == "open"

    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery after recovery time."""
        backend = BackendHealth(name="test", failure_threshold=2, recovery_time=0)

        # Open circuit
        backend.record_failure("failure 1")
        backend.record_failure("failure 2")
        assert backend.circuit_open is True

        # With recovery_time=0, should immediately be in half-open
        assert backend.can_use() is True
        assert backend.get_status() == "half-open"

        # Record success to close circuit
        backend.record_success()
        assert backend.circuit_open is False
        assert backend.get_status() == "healthy"

    def test_disabled_backend(self):
        """Test disabled backend cannot be used."""
        backend = BackendHealth(name="test")
        backend.enabled = False
        assert backend.can_use() is False
        assert backend.get_status() == "disabled"

    def test_health_score(self):
        """Test health score calculation."""
        backend = BackendHealth(name="test")

        # All successes
        for _ in range(10):
            backend.record_success()
        assert backend.get_health_score() == 1.0

        # Add some failures
        for _ in range(5):
            backend.record_failure("test failure")
        score = backend.get_health_score()
        assert 0.0 <= score <= 1.0
        assert score < 1.0  # Should be less than perfect

    def test_to_dict(self):
        """Test conversion to dictionary."""
        backend = BackendHealth(name="test")
        backend.record_success()
        d = backend.to_dict()

        assert d["name"] == "test"
        assert d["enabled"] is True
        assert d["status"] == "healthy"
        assert d["total_requests"] == 1
        assert d["total_successes"] == 1
        assert "health_score" in d
        assert "failure_threshold" in d

    def test_reset(self):
        """Test resetting statistics."""
        backend = BackendHealth(name="test")
        backend.record_success()
        backend.record_failure("test")
        assert backend.total_requests == 2

        backend.reset()
        assert backend.total_requests == 0
        assert backend.consecutive_failures == 0
        assert backend.circuit_open is False


class TestSearchHealthManager:
    """Tests for SearchHealthManager class."""

    def test_initialization(self):
        """Test manager initialization."""
        manager = SearchHealthManager(["bing", "duckduckgo", "google"])
        assert len(manager._backends) == 3
        assert manager.get_backend("bing") is not None
        assert manager.get_backend("nonexistent") is None

    def test_record_success_and_failure(self):
        """Test recording success and failure through manager."""
        manager = SearchHealthManager(["bing", "duckduckgo"])

        manager.record_success("bing")
        manager.record_failure("duckduckgo", "timeout")

        bing = manager.get_backend("bing")
        ddg = manager.get_backend("duckduckgo")

        assert bing.total_successes == 1
        assert ddg.total_failures == 1
        assert ddg.last_failure_reason == "timeout"

    def test_get_available_backends(self):
        """Test filtering available backends."""
        manager = SearchHealthManager(
            ["bing", "duckduckgo", "google"],
            failure_threshold=2,
        )

        # Initially all available
        available = manager.get_available_backends(["bing", "duckduckgo", "google"])
        assert len(available) == 3

        # Open circuit for google
        manager.record_failure("google", "failure 1")
        manager.record_failure("google", "failure 2")

        # Google should no longer be available
        available = manager.get_available_backends(["bing", "duckduckgo", "google"])
        assert "google" not in available
        assert "bing" in available
        assert "duckduckgo" in available

    def test_health_report(self):
        """Test health report generation."""
        manager = SearchHealthManager(["bing", "duckduckgo"])

        manager.record_success("bing")
        manager.record_failure("duckduckgo", "timeout")

        report = manager.get_health_report()

        assert report["total_backends"] == 2
        assert report["total_requests"] == 2
        assert report["total_successes"] == 1
        assert report["total_failures"] == 1
        assert "overall_health_score" in report
        assert "backends" in report
        assert len(report["backends"]) == 2
        assert "timestamp" in report

    def test_enable_disable_backend(self):
        """Test enabling and disabling backends."""
        manager = SearchHealthManager(["bing", "duckduckgo"])

        assert manager.disable_backend("bing") is True
        assert manager.enable_backend("bing") is True
        assert manager.disable_backend("nonexistent") is False

    def test_reset_all(self):
        """Test resetting all backends."""
        manager = SearchHealthManager(["bing", "duckduckgo"])
        manager.record_success("bing")
        manager.record_failure("duckduckgo", "test")

        manager.reset_all()

        for backend in manager._backends.values():
            assert backend.total_requests == 0
            assert backend.circuit_open is False
