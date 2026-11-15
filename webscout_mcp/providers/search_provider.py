"""Standardized Search Provider interface for webscout-mcp.

This module defines the standardized interface that all search providers
must implement, ensuring consistent behavior and easy extensibility.

Standard Return Format:
    SearchResponse contains:
    - query: The search query
    - results: List of SearchResult
    - provider: Provider name (e.g., "bing", "duckduckgo", "serpapi")
    - latency_ms: Time taken for the search in milliseconds
    - status: "success", "empty", "error"
    - error_type: Standard error code (if status is "error")
    - retryable: Whether the request can be retried
    - error_message: Human-readable error message (if any)

This allows SearchService to:
- SerpAPI -> fail -> Bing -> fail -> DuckDuckGo (fallback)
- Or: concurrent search -> dedup -> rank -> return

Adding new providers (Brave, Google API, Tavily, Exa, etc.) requires
only implementing this interface - no changes to core logic needed.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderHealthStatus(str, Enum):
    """Health status of a provider."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CIRCUIT_OPEN = "circuit_open"
    UNKNOWN = "unknown"


@dataclass
class SearchRequest:
    """Standardized search request.

    All search providers receive this standardized request object,
    ensuring consistent parameter handling across providers.
    """

    query: str
    max_results: int = 10
    safe_search: bool = False
    region: str = "wt-wt"
    language: str = "en"
    country: str = "us"
    timeout: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.query = self.query.strip()
        if self.max_results < 1:
            self.max_results = 1
        if self.max_results > 100:
            self.max_results = 100


@dataclass
class ProviderHealth:
    """Health status of a search provider.

    Used by SearchService to make routing decisions (fallback, circuit breaker).
    """

    provider: str
    status: ProviderHealthStatus = ProviderHealthStatus.UNKNOWN
    latency_ms: float = 0.0
    success_rate: float = 1.0
    error_count: int = 0
    last_error: str | None = None
    last_check: float = field(default_factory=time.time)
    circuit_open: bool = False
    circuit_reset_at: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def is_available(self) -> bool:
        """Check if the provider is available for requests."""
        if self.circuit_open:
            if self.circuit_reset_at and time.time() >= self.circuit_reset_at:
                return True  # Half-open
            return False
        return self.status in (
            ProviderHealthStatus.HEALTHY,
            ProviderHealthStatus.DEGRADED,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "provider": self.provider,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "success_rate": self.success_rate,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "circuit_open": self.circuit_open,
            "circuit_reset_at": self.circuit_reset_at,
        }


@dataclass
class SearchProvider(ABC):
    """Abstract base class for all search providers.

    All search providers must implement this interface to ensure
    consistent behavior and easy extensibility.

    To add a new search provider:
    1. Create a class that inherits from SearchProvider
    2. Implement the search() method
    3. Implement the health() method
    4. Register it with SearchService

    No changes to core SearchService logic are needed.
    """

    name: str = "base"

    def __init__(self, config: Any) -> None:
        self.config = config
        self._health = ProviderHealth(provider=self.name)

    @abstractmethod
    async def search(self, request: SearchRequest) -> SearchResponse:
        """Perform a search and return standardized response.

        Args:
            request: Standardized search request

        Returns:
            Standardized search response with results, status, latency, etc.
        """
        ...

    @abstractmethod
    async def health(self) -> ProviderHealth:
        """Get the current health status of the provider.

        Returns:
            ProviderHealth with status, latency, success rate, etc.
        """
        ...

    async def close(self) -> None:
        """Close any resources held by the provider."""

    def _measure_latency(self, start_time: float) -> float:
        """Calculate latency in milliseconds."""
        return (time.time() - start_time) * 1000

    def _update_health_from_response(self, response: SearchResponse) -> None:
        """Update provider health based on search response."""
        self._health.latency_ms = response.latency_ms
        self._health.last_check = time.time()

        if response.is_success:
            self._health.status = ProviderHealthStatus.HEALTHY
            self._health.error_count = 0
            self._health.last_error = None
        elif response.is_empty:
            self._health.status = ProviderHealthStatus.DEGRADED
        elif response.is_error:
            self._health.error_count += 1
            self._health.last_error = response.error_message
            if self._health.error_count >= 5:
                self._health.status = ProviderHealthStatus.UNHEALTHY
            else:
                self._health.status = ProviderHealthStatus.DEGRADED

    def get_health(self) -> ProviderHealth:
        """Get the current cached health status."""
        return self._health


# SearchResult is defined in services/search.py and re-exported here so
# historical `from webscout_mcp.providers.search_provider import SearchResult`
# call sites keep working.
from ..services.search import SearchResult  # noqa: E402,F401

# SearchStatus / SearchResponse moved to services/transfer_types.py
# (layer direction fix); re-exported here for compatibility.
# SearchFailureKind also moved down (SearchResponse references it).
from ..services.transfer_types import (  # noqa: E402,F401
    SearchFailureKind,  # noqa: E402,F401
    SearchResponse,
    SearchStatus,
)
