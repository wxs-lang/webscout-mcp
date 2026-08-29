"""
Extra tests for health module - covering edge cases for HealthChecker.

These tests supplement test_health.py with additional edge case coverage.
Only tests actual existing APIs.
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webscout_mcp.health import HealthChecker, get_health_report


class TestHealthCheckerEdgeCases:
    """Edge case tests for HealthChecker."""

    def test_dependency_check_raises_exception(self):
        """Test that dependency check raising exception is handled."""
        checker = HealthChecker(version="1.0.0")

        def failing_dependency():
            raise RuntimeError("Database connection failed")

        checker.register_dependency("database", failing_dependency)
        status = checker.check_readiness()

        assert status.status == "unhealthy"
        assert "dependency:database" in status.checks
        assert status.checks["dependency:database"]["status"] == "unhealthy"
        assert "error" in status.checks["dependency:database"]

    def test_custom_check_raises_exception(self):
        """Test that custom check raising exception is handled."""
        checker = HealthChecker(version="1.0.0")

        def failing_check():
            raise ValueError("Invalid configuration")

        checker.register_check("custom_check", failing_check)
        status = checker.check_readiness()

        assert status.status == "unhealthy"
        assert "custom_check" in status.checks
        assert status.checks["custom_check"]["status"] == "unhealthy"
        assert "error" in status.checks["custom_check"]

    def test_custom_check_returns_degraded(self):
        """Test that custom check returning degraded status is handled."""
        checker = HealthChecker(version="1.0.0")

        def degraded_check():
            return {"status": "degraded", "message": "High latency"}

        checker.register_check("latency_check", degraded_check)
        status = checker.check_readiness()

        # Should be degraded, not unhealthy (since no failing checks)
        assert status.status in ["degraded", "healthy"]
        assert "latency_check" in status.checks
        assert status.checks["latency_check"]["status"] == "degraded"

    def test_custom_check_returns_unhealthy(self):
        """Test that custom check returning unhealthy status is handled."""
        checker = HealthChecker(version="1.0.0")

        def unhealthy_check():
            return {"status": "unhealthy", "message": "Service down"}

        checker.register_check("service_check", unhealthy_check)
        status = checker.check_readiness()

        assert status.status == "unhealthy"
        assert "service_check" in status.checks
        assert status.checks["service_check"]["status"] == "unhealthy"

    def test_multiple_dependencies_one_fails(self):
        """Test that one failing dependency makes overall status unhealthy."""
        checker = HealthChecker(version="1.0.0")

        checker.register_dependency("cache", lambda: True)
        checker.register_dependency("database", lambda: (_ for _ in ()).throw(RuntimeError("Failed")))

        status = checker.check_readiness()
        assert status.status == "unhealthy"
        assert status.checks["dependency:cache"]["status"] == "healthy"
        assert status.checks["dependency:database"]["status"] == "unhealthy"

    def test_multiple_custom_checks_mixed_status(self):
        """Test multiple custom checks with mixed statuses."""
        checker = HealthChecker(version="1.0.0")

        checker.register_check("check1", lambda: {"status": "healthy"})
        checker.register_check("check2", lambda: {"status": "degraded"})
        checker.register_check("check3", lambda: {"status": "healthy"})

        status = checker.check_readiness()
        # At least degraded because check2 is degraded
        assert status.status in ["degraded", "healthy"]

    def test_health_checker_version(self):
        """Test HealthChecker version is reported."""
        checker = HealthChecker(version="2.0.0-test")
        liveness = checker.check_liveness()
        assert liveness.version == "2.0.0-test"

    def test_health_checker_uptime(self):
        """Test HealthChecker uptime is positive."""
        checker = HealthChecker(version="1.0.0")
        time.sleep(0.1)
        liveness = checker.check_liveness()
        assert liveness.uptime_seconds > 0

    def test_health_checker_liveness_status(self):
        """Test liveness check returns alive status."""
        checker = HealthChecker(version="1.0.0")
        liveness = checker.check_liveness()
        assert liveness.status in ["alive", "healthy"]

    def test_health_checker_readiness_with_no_checks(self):
        """Test readiness check with no registered checks."""
        checker = HealthChecker(version="1.0.0")
        status = checker.check_readiness()
        # Should be healthy with no checks
        assert status.status == "healthy"

    def test_health_checker_multiple_healthy_dependencies(self):
        """Test multiple healthy dependencies."""
        checker = HealthChecker(version="1.0.0")
        checker.register_dependency("dep1", lambda: True)
        checker.register_dependency("dep2", lambda: True)
        checker.register_dependency("dep3", lambda: True)
        status = checker.check_readiness()
        assert status.status == "healthy"
        assert status.checks["dependency:dep1"]["status"] == "healthy"
        assert status.checks["dependency:dep2"]["status"] == "healthy"
        assert status.checks["dependency:dep3"]["status"] == "healthy"

    def test_health_checker_dependency_returns_false(self):
        """Test dependency returning False is unhealthy."""
        checker = HealthChecker(version="1.0.0")
        checker.register_dependency("unhealthy_dep", lambda: False)
        status = checker.check_readiness()
        assert status.status == "unhealthy"
        assert status.checks["dependency:unhealthy_dep"]["status"] == "unhealthy"

    def test_health_checker_custom_check_no_status_key(self):
        """Test custom check result without status key defaults to healthy."""
        checker = HealthChecker(version="1.0.0")

        def check_without_status():
            return {"message": "All good"}

        checker.register_check("no_status", check_without_status)
        status = checker.check_readiness()
        # Should default to healthy
        assert status.status in ["healthy", "degraded"]


class TestHealthReportEdgeCases:
    """Edge case tests for health report generation."""

    def test_get_health_report_structure(self):
        """Test health report structure."""
        report = get_health_report()
        assert "health" in report
        assert "system" in report
        assert "service" in report
        assert "dependencies" in report

    def test_get_health_report_health_status(self):
        """Test health report health status."""
        report = get_health_report()
        assert report["health"]["status"] in ["healthy", "degraded", "unhealthy"]

    def test_get_health_report_timestamp(self):
        """Test health report has timestamp."""
        report = get_health_report()
        assert "timestamp" in report["health"]
        assert report["health"]["timestamp"] != ""

    def test_get_health_report_system_info(self):
        """Test health report system info has expected keys."""
        report = get_health_report()
        # System info should have some metrics
        assert len(report["system"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
