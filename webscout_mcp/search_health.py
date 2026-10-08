"""
Search backend health management with circuit breaker pattern.

Tracks backend health, implements circuit breaking for failing backends,
and provides health status reporting.

v1.9.0 fixes:
- Distinguishes unobserved/unknown from truly healthy (no more default 1.0)
- Explicit circuit state machine: closed -> open -> half-open -> closed
- Strict half-open probe concurrency limits
- Monotonic clock for internal interval calculations
- Result classification: success / empty / hard_failure / invalid_query /
  timeout / circuit_skipped / unavailable
- Backward-compatible JSON fields
"""

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

# Circuit states
CIRCUIT_CLOSED = "closed"
CIRCUIT_OPEN = "open"
CIRCUIT_HALF_OPEN = "half-open"

# Result classifications
RESULT_SUCCESS = "success"
RESULT_EMPTY = "empty_result"
RESULT_HARD_FAILURE = "hard_failure"
RESULT_INVALID_QUERY = "invalid_query"
RESULT_TIMEOUT = "timeout"
RESULT_CIRCUIT_SKIPPED = "circuit_skipped"
RESULT_UNAVAILABLE = "unavailable"

# Max recent failures to retain for observability
_MAX_RECENT_FAILURES = 10


@dataclass
class BackendHealth:
    """Health status for a single search backend.

    v1.9.0: Uses monotonic clock internally for interval calculations.
    The ``observed`` flag distinguishes backends with no request history
    from those that are genuinely healthy.
    """

    name: str
    enabled: bool = True

    # Request statistics
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0
    total_empty: int = 0
    total_timeouts: int = 0
    total_invalid_queries: int = 0
    total_circuit_skips: int = 0
    total_unavailable: int = 0

    # Circuit breaker state
    circuit_state: str = CIRCUIT_CLOSED  # closed | open | half-open
    circuit_open_time: float | None = None  # wall-clock when opened (backward compat)
    circuit_open_monotonic: float | None = None  # monotonic time when opened
    half_open_requests_in_flight: int = 0
    half_open_successes: int = 0
    circuit_open_count: int = 0  # Total times circuit has opened
    circuit_recovery_count: int = 0  # Total times circuit has recovered to closed

    # Timestamps (wall clock for external reporting)
    last_failure_time: float | None = None
    last_success_time: float | None = None
    last_failure_reason: str | None = None
    last_recovery_time: float | None = None

    # Recent failures for observability
    recent_failures: deque = field(default_factory=lambda: deque(maxlen=_MAX_RECENT_FAILURES))

    # Configuration
    failure_threshold: int = 5  # Open circuit after N consecutive failures
    recovery_time: int = 60  # Seconds before attempting recovery (monotonic)
    half_open_max_requests: int = 1  # Max concurrent probes in half-open
    half_open_success_threshold: int = 1  # Successes needed to close from half-open

    @property
    def observed(self) -> bool:
        """Whether this backend has ever been observed (any request recorded)."""
        return self.total_requests > 0

    @property
    def circuit_open(self) -> bool:
        """Backward-compatible alias: True if circuit is open or half-open."""
        return self.circuit_state in (CIRCUIT_OPEN, CIRCUIT_HALF_OPEN)

    def _now_monotonic(self) -> float:
        """Get current monotonic time for interval calculations."""
        return time.monotonic()

    def _now_wall(self) -> float:
        """Get current wall-clock time for external reporting."""
        return time.time()

    def record_success(self) -> None:
        """Record a successful request."""
        self.total_requests += 1
        self.total_successes += 1
        self.consecutive_successes += 1
        self.consecutive_failures = 0
        self.last_success_time = self._now_wall()

        # Handle half-open -> closed transition
        if self.circuit_state == CIRCUIT_HALF_OPEN:
            self.half_open_successes += 1
            if self.half_open_successes >= self.half_open_success_threshold:
                self._close_circuit()

    def record_empty(self) -> None:
        """Record a soft miss (provider completed but had no results).

        This is NOT a hard failure: does not increment consecutive_failures,
        does not trip the circuit breaker, does not pollute error rate.
        Still counts as a request so availability scoring stays honest.
        """
        self.total_requests += 1
        self.total_empty += 1
        self.last_success_time = self._now_wall()

    def record_failure(self, reason: str = "unknown") -> None:
        """Record a hard failed request."""
        self.total_requests += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = self._now_wall()
        self.last_failure_reason = reason
        self.recent_failures.append(
            {
                "time": self.last_failure_time,
                "reason": reason,
                "consecutive": self.consecutive_failures,
            }
        )

        if self.circuit_state == CIRCUIT_HALF_OPEN:
            # Half-open probe failed: reopen circuit and reset recovery timer
            self._open_circuit()
        elif self.circuit_state == CIRCUIT_CLOSED:
            # Open circuit if we hit the failure threshold
            if self.consecutive_failures >= self.failure_threshold:
                self._open_circuit()

    def record_timeout(self, reason: str = "timeout") -> None:
        """Record a timeout failure. Timeouts count as hard failures."""
        self.total_timeouts += 1
        self.record_failure(reason=reason)

    def record_invalid_query(self) -> None:
        """Record an invalid query. Request-level: does NOT pollute provider health."""
        self.total_invalid_queries += 1
        # Do NOT increment total_requests or affect circuit state.
        # Invalid queries are a caller problem, not a provider problem.

    def record_circuit_skipped(self) -> None:
        """Record that a request was skipped because circuit was open."""
        self.total_circuit_skips += 1
        # No health mutation: the provider wasn't actually called.

    def record_unavailable(self) -> None:
        """Record that a provider was unavailable (not registered / disabled)."""
        self.total_unavailable += 1
        # No health mutation: the provider wasn't actually called.

    def _open_circuit(self) -> None:
        """Transition to open state."""
        if self.circuit_state != CIRCUIT_OPEN:
            self.circuit_open_count += 1
        self.circuit_state = CIRCUIT_OPEN
        self.circuit_open_time = self._now_wall()
        self.circuit_open_monotonic = self._now_monotonic()
        self.half_open_requests_in_flight = 0
        self.half_open_successes = 0

    def _close_circuit(self) -> None:
        """Transition to closed state (recovery)."""
        self.circuit_state = CIRCUIT_CLOSED
        self.circuit_open_time = None
        self.circuit_open_monotonic = None
        self.half_open_requests_in_flight = 0
        self.half_open_successes = 0
        self.consecutive_failures = 0
        self.circuit_recovery_count += 1
        self.last_recovery_time = self._now_wall()

    def _transition_to_half_open(self) -> None:
        """Transition from open to half-open (recovery timer expired)."""
        self.circuit_state = CIRCUIT_HALF_OPEN
        self.half_open_requests_in_flight = 0
        self.half_open_successes = 0

    def can_use(self) -> bool:
        """Check if this backend can be used right now.

        Returns:
            True if the backend is available, False if circuit is open
            or half-open probe limit reached.
        """
        if not self.enabled:
            return False

        if self.circuit_state == CIRCUIT_CLOSED:
            return True

        if self.circuit_state == CIRCUIT_OPEN:
            # Check if recovery time has passed (using monotonic clock)
            if self.circuit_open_monotonic is not None:
                elapsed = self._now_monotonic() - self.circuit_open_monotonic
                if elapsed >= self.recovery_time:
                    self._transition_to_half_open()
                    return True
            return False

        if self.circuit_state == CIRCUIT_HALF_OPEN:
            # Strict concurrency limit on half-open probes
            return self.half_open_requests_in_flight < self.half_open_max_requests

        return False

    def acquire_half_open_slot(self) -> bool:
        """Attempt to acquire a half-open probe slot. Must be called before
        making a probe request when circuit is half-open.

        Returns:
            True if slot acquired, False if limit reached.
        """
        if self.circuit_state != CIRCUIT_HALF_OPEN:
            return True  # Not in half-open, no slot needed
        if self.half_open_requests_in_flight >= self.half_open_max_requests:
            return False
        self.half_open_requests_in_flight += 1
        return True

    def release_half_open_slot(self) -> None:
        """Release a previously acquired half-open probe slot."""
        if self.half_open_requests_in_flight > 0:
            self.half_open_requests_in_flight -= 1

    def get_health_score(self) -> float | None:
        """Get health score from 0.0 (unhealthy) to 1.0 (healthy).

        Returns None when the backend has never been observed, so callers
        can distinguish "unknown" from "healthy".
        """
        if not self.observed:
            return None  # Unobserved: not healthy, just unknown

        success_rate = self.total_successes / self.total_requests

        # Penalize for open circuit
        if self.circuit_state == CIRCUIT_OPEN:
            success_rate *= 0.3
        elif self.circuit_state == CIRCUIT_HALF_OPEN:
            success_rate *= 0.5

        # Penalize for recent failures
        if self.last_failure_time:
            time_since_failure = self._now_wall() - self.last_failure_time
            if time_since_failure < 60:  # Less than 1 minute ago
                success_rate *= 0.7
            elif time_since_failure < 300:  # Less than 5 minutes ago
                success_rate *= 0.9

        return max(0.0, min(1.0, success_rate))

    def get_status(self) -> str:
        """Get human-readable status."""
        if not self.enabled:
            return "disabled"
        if not self.observed:
            return "unobserved"
        if self.circuit_state == CIRCUIT_OPEN:
            return "open"
        if self.circuit_state == CIRCUIT_HALF_OPEN:
            return "half-open"
        if self.consecutive_failures > 0:
            return "degraded"
        return "healthy"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for reporting.

        Backward-compatible: all original fields preserved.
        New fields added for v1.9.0 observability.
        """
        health_score = self.get_health_score()
        return {
            # Original fields (backward compatible)
            "name": self.name,
            "enabled": self.enabled,
            "status": self.get_status(),
            "health_score": round(health_score, 3) if health_score is not None else None,
            "total_requests": self.total_requests,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "circuit_open": self.circuit_open,  # backward-compat alias
            "last_failure_reason": self.last_failure_reason,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "failure_threshold": self.failure_threshold,
            "recovery_time": self.recovery_time,
            # v1.9.0 new fields
            "observed": self.observed,
            "circuit_state": self.circuit_state,
            "total_empty": self.total_empty,
            "total_timeouts": self.total_timeouts,
            "total_invalid_queries": self.total_invalid_queries,
            "total_circuit_skips": self.total_circuit_skips,
            "total_unavailable": self.total_unavailable,
            "circuit_open_count": self.circuit_open_count,
            "circuit_recovery_count": self.circuit_recovery_count,
            "half_open_requests_in_flight": self.half_open_requests_in_flight,
            "last_recovery_time": self.last_recovery_time,
            "recent_failures": list(self.recent_failures),
        }

    def reset(self) -> None:
        """Reset all statistics."""
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.total_requests = 0
        self.total_failures = 0
        self.total_successes = 0
        self.total_empty = 0
        self.total_timeouts = 0
        self.total_invalid_queries = 0
        self.total_circuit_skips = 0
        self.total_unavailable = 0
        self.last_failure_time = None
        self.last_success_time = None
        self.last_failure_reason = None
        self.last_recovery_time = None
        self.circuit_state = CIRCUIT_CLOSED
        self.circuit_open_monotonic = None
        self.half_open_requests_in_flight = 0
        self.half_open_successes = 0
        self.circuit_open_count = 0
        self.circuit_recovery_count = 0
        self.recent_failures.clear()


class SearchHealthManager:
    """Manages health status for all search backends.

    SearchService is the production authority for health state.
    This manager tracks per-backend circuit breakers and statistics.
    """

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

    def record_empty(self, backend_name: str) -> None:
        """Record a soft miss (completed with no results), not a hard failure."""
        if backend_name in self._backends:
            self._backends[backend_name].record_empty()

    def record_timeout(self, backend_name: str, reason: str = "timeout") -> None:
        """Record a timeout failure for a backend."""
        if backend_name in self._backends:
            self._backends[backend_name].record_timeout(reason)

    def record_invalid_query(self, backend_name: str) -> None:
        """Record an invalid query (request-level, no health pollution)."""
        if backend_name in self._backends:
            self._backends[backend_name].record_invalid_query()

    def record_circuit_skipped(self, backend_name: str) -> None:
        """Record a circuit skip (provider not actually called)."""
        if backend_name in self._backends:
            self._backends[backend_name].record_circuit_skipped()

    def record_unavailable(self, backend_name: str) -> None:
        """Record provider unavailable (not actually called)."""
        if backend_name in self._backends:
            self._backends[backend_name].record_unavailable()

    def get_available_backends(self, backend_names: list[str]) -> list[str]:
        """Filter backend names to only those that are currently available."""
        available = []
        for name in backend_names:
            backend = self._backends.get(name)
            if backend and backend.can_use():
                available.append(name)
        return available

    def get_health_report(self) -> dict[str, Any]:
        """Get comprehensive health report for all backends.

        v1.9.0: overall_health_score is None when no backends have been
        observed, rather than defaulting to 1.0.
        """
        backends = []
        healthy_count = 0
        degraded_count = 0
        open_count = 0
        half_open_count = 0
        disabled_count = 0
        unobserved_count = 0

        for backend in self._backends.values():
            status = backend.get_status()
            if status == "healthy":
                healthy_count += 1
            elif status == "degraded":
                degraded_count += 1
            elif status == "open":
                open_count += 1
            elif status == "half-open":
                half_open_count += 1
            elif status == "disabled":
                disabled_count += 1
            elif status == "unobserved":
                unobserved_count += 1

            backends.append(backend.to_dict())

        total_requests = sum(b.total_requests for b in self._backends.values())
        total_successes = sum(b.total_successes for b in self._backends.values())
        total_failures = sum(b.total_failures for b in self._backends.values())
        total_observed = sum(1 for b in self._backends.values() if b.observed)

        # Overall health: only average over observed backends
        observed_scores = [b.get_health_score() for b in self._backends.values() if b.observed]
        if observed_scores:
            overall_health: float | None = sum(observed_scores) / len(observed_scores)
        else:
            overall_health = None  # Nothing observed yet

        return {
            "overall_health_score": round(overall_health, 3) if overall_health is not None else None,
            "total_backends": len(self._backends),
            "observed_backends": total_observed,
            "unobserved_backends": unobserved_count,
            "healthy_backends": healthy_count,
            "degraded_backends": degraded_count,
            "open_circuits": open_count,
            "half_open_circuits": half_open_count,
            "disabled_backends": disabled_count,
            "total_requests": total_requests,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "overall_success_rate": (round(total_successes / total_requests, 3) if total_requests > 0 else None),
            "backends": backends,
            "timestamp": time.time(),
            "circuit_breaker_authority": "SearchHealthManager",
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
    "CIRCUIT_CLOSED",
    "CIRCUIT_OPEN",
    "CIRCUIT_HALF_OPEN",
    "RESULT_SUCCESS",
    "RESULT_EMPTY",
    "RESULT_HARD_FAILURE",
    "RESULT_INVALID_QUERY",
    "RESULT_TIMEOUT",
    "RESULT_CIRCUIT_SKIPPED",
    "RESULT_UNAVAILABLE",
]
