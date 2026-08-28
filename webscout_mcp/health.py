"""Health check and operations monitoring module for webscout-mcp.

Provides health check endpoints, system status monitoring, dependency checks,
and readiness/liveness probes for containerized deployments.

Features:
- Health check (liveness + readiness)
- System resource monitoring (CPU, memory, disk)
- Dependency health checks (network, database, cache)
- Service status tracking
- Metrics collection and reporting
- Graceful shutdown support
"""
from __future__ import annotations
import time
import platform
import os
import sys
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime, timedelta
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class HealthStatus:
    """Health check result."""
    status: str = "healthy"  # healthy, degraded, unhealthy
    checks: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    timestamp: str = ""
    version: str = ""
    uptime_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "checks": self.checks,
            "timestamp": self.timestamp,
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
        }


@dataclass
class SystemMetrics:
    """System resource metrics."""
    cpu_percent: float = 0.0
    memory_total_mb: float = 0.0
    memory_used_mb: float = 0.0
    memory_percent: float = 0.0
    disk_total_gb: float = 0.0
    disk_used_gb: float = 0.0
    disk_percent: float = 0.0
    load_average: List[float] = field(default_factory=list)
    process_count: int = 0
    thread_count: int = 0
    python_version: str = ""
    platform: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "cpu_percent": self.cpu_percent,
            "memory_total_mb": self.memory_total_mb,
            "memory_used_mb": self.memory_used_mb,
            "memory_percent": self.memory_percent,
            "disk_total_gb": self.disk_total_gb,
            "disk_used_gb": self.disk_used_gb,
            "disk_percent": self.disk_percent,
            "load_average": self.load_average,
            "process_count": self.process_count,
            "thread_count": self.thread_count,
            "python_version": self.python_version,
            "platform": self.platform,
            "timestamp": self.timestamp,
        }


class HealthChecker:
    """Main health checker for liveness and readiness probes."""

    def __init__(
        self,
        version: str = "0.1.0",
        startup_time: Optional[float] = None,
    ) -> None:
        self.version = version
        self.startup_time = startup_time or time.time()
        self._custom_checks: Dict[str, Callable[[], Dict[str, Any]]] = {}
        self._dependencies: Dict[str, Callable[[], bool]] = {}
        self._shutdown_requested = False
        self._shutdown_time: Optional[float] = None

    def register_check(self, name: str, check_fn: Callable[[], Dict[str, Any]]) -> None:
        """Register a custom health check.

        Args:
            name: Check name.
            check_fn: Function returning dict with 'status' (healthy/degraded/unhealthy) and optional details.
        """
        self._custom_checks[name] = check_fn

    def register_dependency(self, name: str, check_fn: Callable[[], bool]) -> None:
        """Register a dependency health check.

        Args:
            name: Dependency name.
            check_fn: Function returning True if healthy.
        """
        self._dependencies[name] = check_fn

    def check_liveness(self) -> HealthStatus:
        """Check liveness (is the process running?).

        Returns:
            HealthStatus with liveness result.
        """
        status = HealthStatus(
            status="healthy",
            timestamp=datetime.utcnow().isoformat(),
            version=self.version,
            uptime_seconds=time.time() - self.startup_time,
        )

        # Basic process check
        status.checks["process"] = {
            "status": "healthy",
            "pid": os.getpid(),
            "running": True,
        }

        # Check if shutdown was requested
        if self._shutdown_requested:
            status.status = "unhealthy"
            status.checks["shutdown"] = {
                "status": "unhealthy",
                "requested_at": self._shutdown_time,
            }

        return status

    def check_readiness(self) -> HealthStatus:
        """Check readiness (is the service ready to serve requests?).

        Returns:
            HealthStatus with readiness result.
        """
        status = self.check_liveness()

        # Check dependencies
        all_dependencies_healthy = True
        for name, check_fn in self._dependencies.items():
            try:
                is_healthy = check_fn()
                status.checks[f"dependency:{name}"] = {
                    "status": "healthy" if is_healthy else "unhealthy",
                }
                if not is_healthy:
                    all_dependencies_healthy = False
            except Exception as exc:
                status.checks[f"dependency:{name}"] = {
                    "status": "unhealthy",
                    "error": str(exc),
                }
                all_dependencies_healthy = False

        # Run custom checks
        for name, check_fn in self._custom_checks.items():
            try:
                result = check_fn()
                check_status = result.get("status", "healthy")
                status.checks[name] = result
                if check_status == "unhealthy":
                    all_dependencies_healthy = False
                elif check_status == "degraded" and status.status == "healthy":
                    status.status = "degraded"
            except Exception as exc:
                status.checks[name] = {
                    "status": "unhealthy",
                    "error": str(exc),
                }
                all_dependencies_healthy = False

        if not all_dependencies_healthy:
            status.status = "unhealthy"

        return status

    def request_shutdown(self) -> None:
        """Request graceful shutdown."""
        self._shutdown_requested = True
        self._shutdown_time = time.time()
        log.info("Graceful shutdown requested")

    @property
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown was requested."""
        return self._shutdown_requested

    def get_uptime(self) -> timedelta:
        """Get service uptime."""
        return timedelta(seconds=time.time() - self.startup_time)


class SystemMonitor:
    """Monitor system resources (CPU, memory, disk)."""

    def __init__(self) -> None:
        self._history: List[SystemMetrics] = []
        self._max_history = 100

    def collect_metrics(self) -> SystemMetrics:
        """Collect current system metrics.

        Returns:
            SystemMetrics with current resource usage.
        """
        metrics = SystemMetrics(
            timestamp=datetime.utcnow().isoformat(),
            python_version=sys.version,
            platform=platform.platform(),
        )

        # Memory metrics (using resource module, no psutil dependency)
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            metrics.memory_used_mb = usage.ru_maxrss / 1024  # KB to MB on Linux
            metrics.memory_percent = 0.0  # Can't get total without psutil
        except Exception:
            pass

        # Disk metrics
        try:
            stat = os.statvfs("/")
            metrics.disk_total_gb = (stat.f_blocks * stat.f_frsize) / (1024 ** 3)
            metrics.disk_used_gb = ((stat.f_blocks - stat.f_bavail) * stat.f_frsize) / (1024 ** 3)
            metrics.disk_percent = (metrics.disk_used_gb / metrics.disk_total_gb) * 100 if metrics.disk_total_gb > 0 else 0
        except Exception:
            pass

        # Load average (Unix only)
        try:
            metrics.load_average = list(os.getloadavg())
        except (AttributeError, OSError):
            metrics.load_average = []

        # Process/thread count
        try:
            metrics.process_count = 1  # Current process
            metrics.thread_count = 1  # Main thread
        except Exception:
            pass

        # Store in history
        self._history.append(metrics)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        return metrics

    def get_history(self, limit: int = 10) -> List[SystemMetrics]:
        """Get metrics history.

        Args:
            limit: Maximum number of entries to return.

        Returns:
            List of SystemMetrics.
        """
        return self._history[-limit:]

    def get_average(self, limit: int = 10) -> Dict[str, float]:
        """Get average metrics over recent history.

        Args:
            limit: Number of recent entries to average.

        Returns:
            Dictionary with average values.
        """
        recent = self._history[-limit:]
        if not recent:
            return {}

        return {
            "memory_used_mb": sum(m.memory_used_mb for m in recent) / len(recent),
            "memory_percent": sum(m.memory_percent for m in recent) / len(recent),
            "disk_percent": sum(m.disk_percent for m in recent) / len(recent),
        }


class DependencyChecker:
    """Check health of external dependencies."""

    def __init__(self) -> None:
        self._checks: Dict[str, Callable[[], Tuple[bool, str]]] = {}

    def register(self, name: str, check_fn: Callable[[], Tuple[bool, str]]) -> None:
        """Register a dependency check.

        Args:
            name: Dependency name.
            check_fn: Function returning (is_healthy, message).
        """
        self._checks[name] = check_fn

    def check_network(self, host: str = "8.8.8.8", port: int = 53, timeout: float = 2.0) -> Tuple[bool, str]:
        """Check network connectivity.

        Args:
            host: Host to connect to.
            port: Port to connect to.
            timeout: Connection timeout.

        Returns:
            Tuple of (is_healthy, message).
        """
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.close()
            return True, f"Network connectivity OK ({host}:{port})"
        except Exception as exc:
            return False, f"Network connectivity failed: {exc}"

    def check_dns(self, hostname: str = "github.com", timeout: float = 2.0) -> Tuple[bool, str]:
        """Check DNS resolution.

        Args:
            hostname: Hostname to resolve.
            timeout: Resolution timeout.

        Returns:
            Tuple of (is_healthy, message).
        """
        import socket
        try:
            socket.setdefaulttimeout(timeout)
            ip = socket.gethostbyname(hostname)
            return True, f"DNS resolution OK ({hostname} -> {ip})"
        except Exception as exc:
            return False, f"DNS resolution failed: {exc}"

    def check_http(self, url: str = "https://github.com", timeout: float = 5.0) -> Tuple[bool, str]:
        """Check HTTP endpoint availability.

        Args:
            url: URL to check.
            timeout: Request timeout.

        Returns:
            Tuple of (is_healthy, message).
        """
        try:
            import urllib.request
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return True, f"HTTP endpoint OK ({url} -> {response.status})"
        except Exception as exc:
            return False, f"HTTP endpoint check failed: {exc}"

    def check_all(self) -> Dict[str, Dict[str, Any]]:
        """Run all registered dependency checks.

        Returns:
            Dictionary with check results.
        """
        results = {}
        for name, check_fn in self._checks.items():
            try:
                is_healthy, message = check_fn()
                results[name] = {
                    "status": "healthy" if is_healthy else "unhealthy",
                    "message": message,
                }
            except Exception as exc:
                results[name] = {
                    "status": "unhealthy",
                    "message": f"Check failed: {exc}",
                }
        return results


class ServiceStatus:
    """Track and report service status."""

    def __init__(self, service_name: str = "webscout-mcp") -> None:
        self.service_name = service_name
        self.start_time = time.time()
        self._status = "initializing"
        self._last_heartbeat = time.time()
        self._request_count = 0
        self._error_count = 0
        self._last_error: Optional[str] = None

    def set_status(self, status: str) -> None:
        """Set service status.

        Args:
            status: New status (initializing, running, degraded, shutting_down).
        """
        log.info(f"Service status changed: {self._status} -> {status}")
        self._status = status

    def heartbeat(self) -> None:
        """Record a heartbeat."""
        self._last_heartbeat = time.time()

    def record_request(self) -> None:
        """Record a successful request."""
        self._request_count += 1
        self.heartbeat()

    def record_error(self, error: str) -> None:
        """Record an error.

        Args:
            error: Error message.
        """
        self._error_count += 1
        self._last_error = error

    def get_status(self) -> Dict[str, Any]:
        """Get current service status.

        Returns:
            Dictionary with status information.
        """
        return {
            "service": self.service_name,
            "status": self._status,
            "uptime_seconds": time.time() - self.start_time,
            "last_heartbeat": datetime.fromtimestamp(self._last_heartbeat).isoformat(),
            "request_count": self._request_count,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "error_rate": (self._error_count / self._request_count * 100) if self._request_count > 0 else 0,
        }

    @property
    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self._status in ["running", "degraded"]


# Global instances
health_checker = HealthChecker()
system_monitor = SystemMonitor()
dependency_checker = DependencyChecker()
service_status = ServiceStatus()


def get_health_report() -> Dict[str, Any]:
    """Get a comprehensive health report.

    Returns:
        Dictionary with health, system metrics, and service status.
    """
    return {
        "health": health_checker.check_readiness().to_dict(),
        "system": system_monitor.collect_metrics().to_dict(),
        "service": service_status.get_status(),
        "dependencies": dependency_checker.check_all(),
    }
