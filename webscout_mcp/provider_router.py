"""Dynamic Provider Router with health-based scoring.

Implements intelligent provider selection based on:
- Recent success rate (24h / 7d)
- P50 / P95 latency
- Error rate (429, 403, timeout, etc.)
- Circuit breaker state
- Cost tier (free vs paid)
- Provider priority hints

This replaces fixed-order fallback with dynamic routing that adapts
to real-world provider performance.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .logging_config import get_logger

log = get_logger(__name__)


class ProviderCostTier(str, Enum):
    """Cost tier for provider routing decisions."""

    FREE = "free"
    LOW_COST = "low_cost"
    PAID = "paid"
    PREMIUM = "premium"


@dataclass
class ProviderMetrics:
    """Rolling metrics for a single provider."""

    name: str
    window_seconds: int = 86400  # 24 hours

    # Rolling request history
    requests: deque = field(default_factory=lambda: deque(maxlen=1000))
    successes: deque = field(default_factory=lambda: deque(maxlen=1000))
    errors: deque = field(default_factory=lambda: deque(maxlen=1000))
    latencies: deque = field(default_factory=lambda: deque(maxlen=1000))

    # Error type tracking
    error_429: int = 0
    error_403: int = 0
    error_timeout: int = 0
    error_connection: int = 0
    error_other: int = 0

    # Circuit state
    circuit_open: bool = False
    circuit_half_open: bool = False
    circuit_open_since: float = 0.0

    def record_request(self, success: bool, latency_ms: float, error_type: str | None = None) -> None:
        """Record a request outcome."""
        now = time.time()
        self.requests.append(now)
        self.latencies.append((now, latency_ms))

        if success:
            self.successes.append(now)
        else:
            self.errors.append((now, error_type or "unknown"))
            if error_type == "rate_limited":
                self.error_429 += 1
            elif error_type == "forbidden":
                self.error_403 += 1
            elif error_type == "timeout":
                self.error_timeout += 1
            elif error_type == "connection_error":
                self.error_connection += 1
            else:
                self.error_other += 1

    def _prune_old(self, deque_obj: deque) -> None:
        """Remove entries older than window."""
        cutoff = time.time() - self.window_seconds
        while deque_obj and deque_obj[0] < cutoff:
            deque_obj.popleft()

    @property
    def success_rate(self) -> float:
        """Calculate recent success rate (0.0 to 1.0)."""
        self._prune_old(self.requests)
        self._prune_old(self.successes)
        if not self.requests:
            return 1.0  # No requests, assume healthy
        return len(self.successes) / len(self.requests)

    @property
    def error_rate(self) -> float:
        """Calculate recent error rate."""
        return 1.0 - self.success_rate

    @property
    def p50_latency(self) -> float:
        """Calculate P50 latency in ms."""
        return self._percentile_latency(50)

    @property
    def p95_latency(self) -> float:
        """Calculate P95 latency in ms."""
        return self._percentile_latency(95)

    def _percentile_latency(self, percentile: int) -> float:
        """Calculate percentile latency."""
        self._prune_old(self.latencies)
        if not self.latencies:
            return 0.0
        latencies = sorted([lat for _, lat in self.latencies])
        idx = int(len(latencies) * percentile / 100)
        idx = min(idx, len(latencies) - 1)
        return latencies[idx]

    @property
    def total_requests(self) -> int:
        self._prune_old(self.requests)
        return len(self.requests)

    @property
    def total_errors(self) -> int:
        self._prune_old(self.errors)
        return len(self.errors)

    def set_circuit_open(self) -> None:
        """Mark circuit as open."""
        self.circuit_open = True
        self.circuit_half_open = False
        self.circuit_open_since = time.time()

    def set_circuit_half_open(self) -> None:
        """Mark circuit as half-open."""
        self.circuit_open = False
        self.circuit_half_open = True

    def set_circuit_closed(self) -> None:
        """Mark circuit as closed (healthy)."""
        self.circuit_open = False
        self.circuit_half_open = False
        self.circuit_open_since = 0.0

    @property
    def is_available(self) -> bool:
        """Check if provider is available for routing."""
        return not self.circuit_open


@dataclass
class ProviderScore:
    """Health score for a provider."""

    name: str
    score: float  # 0.0 to 100.0, higher is better
    success_rate: float
    p95_latency: float
    error_rate: float
    circuit_open: bool
    cost_tier: ProviderCostTier
    reasons: list[str] = field(default_factory=list)


class ProviderHealthScorer:
    """Calculates health scores for providers based on metrics."""

    # Weights for scoring components
    WEIGHT_SUCCESS_RATE = 0.40
    WEIGHT_LATENCY = 0.25
    WEIGHT_ERROR_RATE = 0.20
    WEIGHT_CIRCUIT = 0.15

    # Latency thresholds (ms)
    LATENCY_EXCELLENT = 200.0
    LATENCY_GOOD = 500.0
    LATENCY_POOR = 2000.0

    def __init__(self, cost_tiers: dict[str, ProviderCostTier] | None = None):
        self.cost_tiers = cost_tiers or {}

    def calculate_score(self, metrics: ProviderMetrics) -> ProviderScore:
        """Calculate overall health score for a provider."""
        reasons: list[str] = []

        # Success rate score (0-100)
        success_score = metrics.success_rate * 100
        if metrics.success_rate >= 0.95:
            reasons.append(f"Excellent success rate: {metrics.success_rate:.1%}")
        elif metrics.success_rate >= 0.80:
            reasons.append(f"Good success rate: {metrics.success_rate:.1%}")
        else:
            reasons.append(f"Poor success rate: {metrics.success_rate:.1%}")

        # Latency score (0-100, lower is better)
        if metrics.p95_latency <= self.LATENCY_EXCELLENT:
            latency_score = 100.0
            reasons.append(f"Excellent P95 latency: {metrics.p95_latency:.0f}ms")
        elif metrics.p95_latency <= self.LATENCY_GOOD:
            latency_score = 80.0
            reasons.append(f"Good P95 latency: {metrics.p95_latency:.0f}ms")
        elif metrics.p95_latency <= self.LATENCY_POOR:
            latency_score = 50.0
            reasons.append(f"Slow P95 latency: {metrics.p95_latency:.0f}ms")
        else:
            latency_score = 20.0
            reasons.append(f"Very slow P95 latency: {metrics.p95_latency:.0f}ms")

        # Error rate score (0-100, lower is better)
        error_score = (1.0 - metrics.error_rate) * 100
        if metrics.error_rate <= 0.05:
            reasons.append(f"Low error rate: {metrics.error_rate:.1%}")
        elif metrics.error_rate <= 0.20:
            reasons.append(f"Moderate error rate: {metrics.error_rate:.1%}")
        else:
            reasons.append(f"High error rate: {metrics.error_rate:.1%}")

        # Circuit score (0 or 100)
        if metrics.circuit_open:
            circuit_score = 0.0
            reasons.append("Circuit breaker OPEN")
        elif metrics.circuit_half_open:
            circuit_score = 50.0
            reasons.append("Circuit breaker HALF-OPEN")
        else:
            circuit_score = 100.0
            reasons.append("Circuit breaker closed")

        # Weighted total
        total_score = (
            success_score * self.WEIGHT_SUCCESS_RATE
            + latency_score * self.WEIGHT_LATENCY
            + error_score * self.WEIGHT_ERROR_RATE
            + circuit_score * self.WEIGHT_CIRCUIT
        )

        cost_tier = self.cost_tiers.get(metrics.name, ProviderCostTier.FREE)

        return ProviderScore(
            name=metrics.name,
            score=round(total_score, 1),
            success_rate=metrics.success_rate,
            p95_latency=metrics.p95_latency,
            error_rate=metrics.error_rate,
            circuit_open=metrics.circuit_open,
            cost_tier=cost_tier,
            reasons=reasons,
        )


class ProviderRouter:
    """Dynamic provider router with health-based selection.

    Replaces fixed-order fallback with intelligent routing based on
    real-time provider health metrics.
    """

    def __init__(
        self,
        provider_names: list[str],
        cost_tiers: dict[str, ProviderCostTier] | None = None,
        prefer_free: bool = True,
        min_score_threshold: float = 30.0,
    ):
        """Initialize the router.

        Args:
            provider_names: List of provider names to manage.
            cost_tiers: Mapping of provider name to cost tier.
            prefer_free: If True, prefer free providers when scores are close.
            min_score_threshold: Minimum score to consider a provider healthy.
        """
        self.metrics: dict[str, ProviderMetrics] = {
            name: ProviderMetrics(name=name) for name in provider_names
        }
        self.scorer = ProviderHealthScorer(cost_tiers=cost_tiers)
        self.prefer_free = prefer_free
        self.min_score_threshold = min_score_threshold
        self.cost_tiers = cost_tiers or {}

    def get_ranked_providers(self) -> list[ProviderScore]:
        """Get providers ranked by health score (best first).

        Returns:
            List of ProviderScore, sorted by score descending.
            Providers with open circuits are moved to the end.
        """
        scores = [self.scorer.calculate_score(m) for m in self.metrics.values()]

        # Sort by score, but put circuit-open providers last
        def sort_key(s: ProviderScore) -> tuple:
            circuit_penalty = 1 if s.circuit_open else 0
            # If prefer_free, give free providers a small boost when scores are close
            free_boost = 0
            if self.prefer_free and s.cost_tier == ProviderCostTier.FREE:
                free_boost = 5.0  # Small boost for free providers
            return (circuit_penalty, -(s.score + free_boost))

        scores.sort(key=sort_key)
        return scores

    def get_next_provider(self, exclude: list[str] | None = None) -> str | None:
        """Get the best available provider.

        Args:
            exclude: List of provider names to exclude (already tried).

        Returns:
            Name of the best available provider, or None if none available.
        """
        exclude = exclude or []
        ranked = self.get_ranked_providers()

        for score in ranked:
            if score.name in exclude:
                continue
            metrics = self.metrics[score.name]
            if not metrics.is_available:
                continue
            if score.score < self.min_score_threshold and not metrics.circuit_half_open:
                # Skip providers with very low scores, but allow half-open for recovery
                continue
            return score.name

        # If no provider meets threshold, return the best available one
        for score in ranked:
            if score.name in exclude:
                continue
            metrics = self.metrics[score.name]
            if metrics.is_available or metrics.circuit_half_open:
                return score.name

        return None

    def record_result(
        self,
        provider_name: str,
        success: bool,
        latency_ms: float,
        error_type: str | None = None,
    ) -> None:
        """Record a request result for a provider."""
        if provider_name in self.metrics:
            self.metrics[provider_name].record_request(success, latency_ms, error_type)

    def set_circuit_open(self, provider_name: str) -> None:
        """Mark a provider's circuit as open."""
        if provider_name in self.metrics:
            self.metrics[provider_name].set_circuit_open()

    def set_circuit_half_open(self, provider_name: str) -> None:
        """Mark a provider's circuit as half-open."""
        if provider_name in self.metrics:
            self.metrics[provider_name].set_circuit_half_open()

    def set_circuit_closed(self, provider_name: str) -> None:
        """Mark a provider's circuit as closed."""
        if provider_name in self.metrics:
            self.metrics[provider_name].set_circuit_closed()

    def get_health_report(self) -> dict[str, Any]:
        """Get a comprehensive health report for all providers."""
        ranked = self.get_ranked_providers()
        return {
            "routing_mode": "dynamic_health_based",
            "prefer_free": self.prefer_free,
            "min_score_threshold": self.min_score_threshold,
            "providers": [
                {
                    "name": s.name,
                    "score": s.score,
                    "success_rate": round(s.success_rate, 3),
                    "p95_latency_ms": round(s.p95_latency, 1),
                    "error_rate": round(s.error_rate, 3),
                    "circuit_open": s.circuit_open,
                    "cost_tier": s.cost_tier.value,
                    "total_requests": self.metrics[s.name].total_requests,
                    "total_errors": self.metrics[s.name].total_errors,
                    "reasons": s.reasons,
                }
                for s in ranked
            ],
        }
