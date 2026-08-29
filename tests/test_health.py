"""Tests for health check and operations monitoring module."""

import time

from webscout_mcp.health import (
    DependencyChecker,
    HealthChecker,
    HealthStatus,
    ServiceStatus,
    SystemMetrics,
    SystemMonitor,
    dependency_checker,
    get_health_report,
    health_checker,
    service_status,
    system_monitor,
)

# ============ HealthStatus Tests ============


class TestHealthStatus:
    """Test HealthStatus class."""

    def test_creation(self):
        status = HealthStatus(status="healthy")
        assert status.status == "healthy"

    def test_to_dict(self):
        status = HealthStatus(
            status="healthy",
            version="1.0.0",
            uptime_seconds=100.5,
        )
        data = status.to_dict()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"
        assert data["uptime_seconds"] == 100.5


# ============ SystemMetrics Tests ============


class TestSystemMetrics:
    """Test SystemMetrics class."""

    def test_creation(self):
        metrics = SystemMetrics(cpu_percent=50.0)
        assert metrics.cpu_percent == 50.0

    def test_to_dict(self):
        metrics = SystemMetrics(
            memory_used_mb=512.0,
            memory_percent=50.0,
            python_version="3.10.0",
        )
        data = metrics.to_dict()
        assert data["memory_used_mb"] == 512.0
        assert data["python_version"] == "3.10.0"


# ============ HealthChecker Tests ============


class TestHealthChecker:
    """Test HealthChecker class."""

    def test_creation(self):
        checker = HealthChecker(version="1.0.0")
        assert checker.version == "1.0.0"
        assert checker.startup_time > 0

    def test_check_liveness(self):
        checker = HealthChecker(version="1.0.0")
        status = checker.check_liveness()
        assert status.status == "healthy"
        assert status.version == "1.0.0"
        assert status.uptime_seconds >= 0
        assert "process" in status.checks

    def test_check_readiness_no_dependencies(self):
        checker = HealthChecker(version="1.0.0")
        status = checker.check_readiness()
        assert status.status == "healthy"

    def test_register_dependency_healthy(self):
        checker = HealthChecker()
        checker.register_dependency("test_dep", lambda: True)
        status = checker.check_readiness()
        assert status.status == "healthy"
        assert "dependency:test_dep" in status.checks

    def test_register_dependency_unhealthy(self):
        checker = HealthChecker()
        checker.register_dependency("test_dep", lambda: False)
        status = checker.check_readiness()
        assert status.status == "unhealthy"

    def test_register_custom_check_healthy(self):
        checker = HealthChecker()
        checker.register_check("custom", lambda: {"status": "healthy", "detail": "ok"})
        status = checker.check_readiness()
        assert status.status == "healthy"
        assert "custom" in status.checks

    def test_register_custom_check_degraded(self):
        checker = HealthChecker()
        checker.register_check("custom", lambda: {"status": "degraded", "detail": "slow"})
        status = checker.check_readiness()
        assert status.status == "degraded"

    def test_register_custom_check_unhealthy(self):
        checker = HealthChecker()
        checker.register_check("custom", lambda: {"status": "unhealthy", "detail": "failed"})
        status = checker.check_readiness()
        assert status.status == "unhealthy"

    def test_request_shutdown(self):
        checker = HealthChecker()
        assert checker.is_shutdown_requested is False
        checker.request_shutdown()
        assert checker.is_shutdown_requested is True
        status = checker.check_liveness()
        assert status.status == "unhealthy"

    def test_get_uptime(self):
        checker = HealthChecker()
        time.sleep(0.01)
        uptime = checker.get_uptime()
        assert uptime.total_seconds() >= 0.01

    def test_global_health_checker(self):
        assert health_checker is not None
        assert isinstance(health_checker, HealthChecker)


# ============ SystemMonitor Tests ============


class TestSystemMonitor:
    """Test SystemMonitor class."""

    def test_creation(self):
        monitor = SystemMonitor()
        assert monitor is not None

    def test_collect_metrics(self):
        monitor = SystemMonitor()
        metrics = monitor.collect_metrics()
        assert metrics.timestamp != ""
        assert metrics.python_version != ""
        assert metrics.platform != ""

    def test_get_history(self):
        monitor = SystemMonitor()
        monitor.collect_metrics()
        monitor.collect_metrics()
        history = monitor.get_history(limit=10)
        assert len(history) >= 2

    def test_get_average(self):
        monitor = SystemMonitor()
        monitor.collect_metrics()
        monitor.collect_metrics()
        avg = monitor.get_average(limit=10)
        assert isinstance(avg, dict)

    def test_global_system_monitor(self):
        assert system_monitor is not None
        assert isinstance(system_monitor, SystemMonitor)


# ============ DependencyChecker Tests ============


class TestDependencyChecker:
    """Test DependencyChecker class."""

    def test_creation(self):
        checker = DependencyChecker()
        assert checker is not None

    def test_register_and_check(self):
        checker = DependencyChecker()
        checker.register("test_dep", lambda: (True, "ok"))
        results = checker.check_all()
        assert "test_dep" in results
        assert results["test_dep"]["status"] == "healthy"

    def test_check_unhealthy_dependency(self):
        checker = DependencyChecker()
        checker.register("bad_dep", lambda: (False, "failed"))
        results = checker.check_all()
        assert results["bad_dep"]["status"] == "unhealthy"

    def test_check_dns(self):
        checker = DependencyChecker()
        # This may fail in some environments, just check it doesn't crash
        is_healthy, message = checker.check_dns("localhost", timeout=1.0)
        assert isinstance(is_healthy, bool)
        assert isinstance(message, str)

    def test_check_network(self):
        checker = DependencyChecker()
        # This may fail in some environments, just check it doesn't crash
        is_healthy, message = checker.check_network("127.0.0.1", port=1, timeout=0.5)
        assert isinstance(is_healthy, bool)
        assert isinstance(message, str)

    def test_global_dependency_checker(self):
        assert dependency_checker is not None
        assert isinstance(dependency_checker, DependencyChecker)


# ============ ServiceStatus Tests ============


class TestServiceStatus:
    """Test ServiceStatus class."""

    def test_creation(self):
        status = ServiceStatus(service_name="test-service")
        assert status.service_name == "test-service"
        assert status.start_time > 0

    def test_set_status(self):
        status = ServiceStatus()
        status.set_status("running")
        assert status._status == "running"

    def test_heartbeat(self):
        status = ServiceStatus()
        old_heartbeat = status._last_heartbeat
        time.sleep(0.01)
        status.heartbeat()
        assert status._last_heartbeat > old_heartbeat

    def test_record_request(self):
        status = ServiceStatus()
        assert status._request_count == 0
        status.record_request()
        assert status._request_count == 1

    def test_record_error(self):
        status = ServiceStatus()
        assert status._error_count == 0
        status.record_error("test error")
        assert status._error_count == 1
        assert status._last_error == "test error"

    def test_get_status(self):
        status = ServiceStatus()
        status.set_status("running")
        status.record_request()
        status.record_request()
        status.record_error("error")
        data = status.get_status()
        assert data["service"] == "webscout-mcp"
        assert data["status"] == "running"
        assert data["request_count"] == 2
        assert data["error_count"] == 1
        assert data["error_rate"] == 50.0

    def test_is_healthy_running(self):
        status = ServiceStatus()
        status.set_status("running")
        assert status.is_healthy is True

    def test_is_healthy_degraded(self):
        status = ServiceStatus()
        status.set_status("degraded")
        assert status.is_healthy is True

    def test_is_healthy_initializing(self):
        status = ServiceStatus()
        status.set_status("initializing")
        assert status.is_healthy is False

    def test_global_service_status(self):
        assert service_status is not None
        assert isinstance(service_status, ServiceStatus)


# ============ Health Report Tests ============


class TestHealthReport:
    """Test health report function."""

    def test_get_health_report(self):
        report = get_health_report()
        assert "health" in report
        assert "system" in report
        assert "service" in report
        assert "dependencies" in report
        assert report["health"]["status"] in ["healthy", "degraded", "unhealthy"]
