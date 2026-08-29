"""
Search backend health management with circuit breaker pattern.

Tracks backend health, implements circuit breaking for failing backends,
and provides health status reporting.
"""

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class BackendHealth:
    """Health status for a single search backend."""

    name: str
    enabled: bool = True
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None
    last_failure_reason: str | None = None
    circuit_open: bool = False
    circuit_open_time: float | None = None

    # Configuration
    failure_threshold: int = 5  # Open circuit after N consecutive failures
    recovery_time: int = 60  # Seconds before attempting recovery
    half_open_max_requests: int = 1  # Max requests in half-open state

    def record_success(self) -> None:
        """Record a successful request."""
        self.total_requests += 1
        self.total_successes += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_time = time.time()

        # Close circuit if we had enough consecutive successes in half-open
        if self.circuit_open and self.consecutive_successes >= self.half_open_max_requests:
            self.circuit_open = False
            self.circuit_open_time = None

    def record_failure(self, reason: str = "unknown") -> None:
        """Record a failed request."""
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = time.time()
        self.last_failure_reason = reason

        # Open circuit if we hit the failure threshold
        if self.consecutive_failures >= self.failure_threshold and not self.circuit_open:
            self.circuit_open = True
            self.circuit_open_time = time.time()
        elif self.circuit_open:
            # Half-open request failed - reset the recovery timer
            self.circuit_open_time = time.time()

    def can_use(self) -> bool:
        """Check if this backend can be used.

        Returns:
            True if the backend is available, False if circuit is open.
        """
        if not self.enabled:
            return False

        if not self.circuit_open:
            return True

        # Circuit is open - check if recovery time has passed
        if self.circuit_open_time and (time.time() - self.circuit_open_time) >= self.recovery_time:
            # Move to half-open state (allow limited requests)
            return True

        return False

    def get_health_score(self) -> float:
        """Get health score from 0.0 (unhealthy) to 1.0 (healthy)."""
        if self.total_requests == 0:
            return 1.0  # No requests yet, assume healthy

        success_rate = self.total_successes / self.total_requests

        # Penalize for open circuit
        if self.circuit_open:
            success_rate *= 0.3

        # Penalize for recent failures
        if self.last_failure_time:
            time_since_failure = time.time() - self.last_failure_time
            if time_since_failure < 60:  # Less than 1 minute ago
                success_rate *= 0.7
            elif time_since_failure < 300:  # Less than 5 minutes ago
                success_rate *= 0.9

        return max(0.0, min(1.0, success_rate))

    def get_status(self) -> str:
        """Get human-readable status."""
        if not self.enabled:
            return "disabled"
        if self.circuit_open:
            if self.circuit_open_time and (time.time() - self.circuit_open_time) >= self.recovery_time:
                return "half-open"
            return "open"
        if self.consecutive_failures > 0:
            return "degraded"
        return "healthy"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for reporting."""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "status": self.get_status(),
            "health_score": round(self.get_health_score(), 3),
            "total_requests": self.total_requests,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "circuit_open": self.circuit_open,
            "last_failure_reason": self.last_failure_reason,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "failure_threshold": self.failure_threshold,
            "recovery_time": self.recovery_time,
        }

    def reset(self) -> None:
        """Reset all statistics."""
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.total_requests = 0
        self.total_failures = 0
        self.total_successes = 0
        self.last_failure_time = None
        self.last_success_time = None
        self.last_failure_reason = None
        self.circuit_open = False
        self.circuit_open_time = None


class SearchHealthManager:
    """Manages health status for all search backends."""

    def __init__(
        self,
        backend_names: list[str],
        failure_threshold: int = 5,
        recovery_time: int = 60,
    ) -> None:
        """Initialize health manager.

        Args:
            backend_names: List of backend names to track.
            failure_threshold: Consecutive failures before opening circuit.
            recovery_time: Seconds before attempting circuit recovery.
        """
        self._backends: dict[str, BackendHealth] = {}
        for name in backend_names:
            self._backends[name] = BackendHealth(
                name=name,
                failure_threshold=failure_threshold,
                recovery_time=recovery_time,
            )

    def get_backend(self, name: str) -> BackendHealth | None:
        """Get health status for a specific backend."""
        return self._backends.get(name)

    def record_success(self, backend_name: str) -> None:
        """Record a successful request for a backend."""
        if backend_name in self._backends:
            self._backends[backend_name].record_success()

    def record_failure(self, backend_name: str, reason: str = "unknown") -> None:
        """Record a failed request for a backend."""
        if backend_name in self._backends:
            self._backends[backend_name].record_failure(reason)

    def get_available_backends(self, backend_names: list[str]) -> list[str]:
        """Filter backend names to only those that are currently available.

        Args:
            backend_names: List of backend names to filter.

        Returns:
            List of available backend names in original order.
        """
        available = []
        for name in backend_names:
            backend = self._backends.get(name)
            if backend and backend.can_use():
                available.append(name)
        return available

    def get_health_report(self) -> dict[str, Any]:
        """Get comprehensive health report for all backends."""
        backends = []
        healthy_count = 0
        degraded_count = 0
        open_count = 0
        disabled_count = 0

        for backend in self._backends.values():
            status = backend.get_status()
            if status == "healthy":
                healthy_count += 1
            elif status == "degraded":
                degraded_count += 1
            elif status == "open":
                open_count += 1
            elif status == "disabled":
                disabled_count += 1

            backends.append(backend.to_dict())

        total_requests = sum(b.total_requests for b in self._backends.values())
        total_successes = sum(b.total_successes for b in self._backends.values())
        total_failures = sum(b.total_failures for b in self._backends.values())

        overall_health = (
            sum(b.get_health_score() for b in self._backends.values()) / len(self._backends) if self._backends else 1.0
        )

        return {
            "overall_health_score": round(overall_health, 3),
            "total_backends": len(self._backends),
            "healthy_backends": healthy_count,
            "degraded_backends": degraded_count,
            "open_circuits": open_count,
            "disabled_backends": disabled_count,
            "total_requests": total_requests,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "overall_success_rate": (round(total_successes / total_requests, 3) if total_requests > 0 else 1.0),
            "backends": backends,
            "timestamp": time.time(),
        }

    def reset_all(self) -> None:
        """Reset all backend statistics."""
        for backend in self._backends.values():
            backend.reset()

    def enable_backend(self, name: str) -> bool:
        """Enable a backend."""
        if name in self._backends:
            self._backends[name].enabled = True
            return True
        return False

    def disable_backend(self, name: str) -> bool:
        """Disable a backend."""
        if name in self._backends:
            self._backends[name].enabled = False
            return True
        return False


__all__ = [
    "BackendHealth",
    "SearchHealthManager",
]
