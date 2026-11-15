"""Cross-layer transfer types.

These data classes are produced by providers but consumed by services
(exporter, normalization). Defining them in services keeps the dependency
direction legal — providers may import services (providers is the upper
layer), services may not import providers.

History: they originally lived in providers/crawler.py and
providers/search_provider.py, which made services depend upward. Moving the
classes down and re-exporting from the providers removes those two edges
without touching any other import site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..core.errors import StandardErrorCode
from .fetcher import FetchResult
from .search import SearchResult


class SearchStatus(str, Enum):
    """Status of a search request."""

    SUCCESS = "success"
    EMPTY = "empty"
    ERROR = "error"


class SearchFailureKind(str, Enum):
    """Internal, deterministic failure category for a search provider.

    Used by the SearchRecovery classifier. NOT part of the public MCP
    response; it lives alongside error_type so we can distinguish
    auth / rate-limit / parser / network / server without relying on
    provider-specific strings.
    """

    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTH = "auth"
    PARSER = "parser"
    NETWORK = "network"
    SERVER = "server"
    CONFIG = "config"
    PROVIDER = "provider"
    INVALID_REQUEST = "invalid_request"


@dataclass
class SearchResponse:
    """Standardized search response.

    All search providers return this standardized response object,
    ensuring consistent behavior and easy aggregation by SearchService.
    """

    query: str
    provider: str
    results: list[SearchResult] = field(default_factory=list)
    status: SearchStatus = SearchStatus.SUCCESS
    latency_ms: float = 0.0
    error_type: StandardErrorCode | None = None
    error_message: str | None = None
    retryable: bool = False
    failure_kind: SearchFailureKind | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Auto-detect empty results
        if self.status == SearchStatus.SUCCESS and not self.results:
            self.status = SearchStatus.EMPTY

        # Auto-detect retryable from error type
        if self.error_type and not self.retryable:
            from ..core.errors import RETRYABLE_ERROR_CODES

            if self.error_type in RETRYABLE_ERROR_CODES:
                self.retryable = True

    @property
    def is_success(self) -> bool:
        """Check if the search was successful (has results)."""
        return self.status == SearchStatus.SUCCESS and bool(self.results)

    @property
    def is_empty(self) -> bool:
        """Check if the search returned no results."""
        return self.status == SearchStatus.EMPTY

    @property
    def is_error(self) -> bool:
        """Check if the search failed."""
        return self.status == SearchStatus.ERROR

    @classmethod
    def success(
        cls,
        query: str,
        provider: str,
        results: list[SearchResult],
        latency_ms: float = 0.0,
    ) -> SearchResponse:
        """Create a successful search response."""
        return cls(
            query=query,
            provider=provider,
            results=results,
            status=SearchStatus.SUCCESS,
            latency_ms=latency_ms,
        )

    @classmethod
    def empty(
        cls,
        query: str,
        provider: str,
        latency_ms: float = 0.0,
    ) -> SearchResponse:
        """Create an empty search response."""
        return cls(
            query=query,
            provider=provider,
            results=[],
            status=SearchStatus.EMPTY,
            latency_ms=latency_ms,
        )

    @classmethod
    def error(
        cls,
        query: str,
        provider: str,
        error_type: StandardErrorCode,
        error_message: str = "",
        latency_ms: float = 0.0,
        retryable: bool | None = None,
        failure_kind: SearchFailureKind | None = None,
    ) -> SearchResponse:
        """Create an error search response."""
        return cls(
            query=query,
            provider=provider,
            results=[],
            status=SearchStatus.ERROR,
            latency_ms=latency_ms,
            error_type=error_type,
            error_message=error_message,
            retryable=retryable if retryable is not None else False,
            failure_kind=failure_kind,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "query": self.query,
            "provider": self.provider,
            "results": [
                {
                    "position": r.position,
                    "title": r.title,
                    "url": r.url,
                    "snippet": r.snippet,
                    "backend": r.backend,
                }
                for r in self.results
            ],
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "error_type": self.error_type.value if self.error_type else None,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "result_count": len(self.results),
        }


@dataclass
class CrawlResult:
    """Result of a crawl operation."""

    seed_url: str
    pages_crawled: int = 0
    pages: list[FetchResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    links_found: int = 0
    skipped_robots: int = 0
    retries: int = 0
    avg_response_time: float = 0.0

    # --- Stable-hardening additions (backward-compatible; old keys untouched) ---
    status: str = "success"  # success | partial | failure
    pages_attempted: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0
    pages_blocked_robots: int = 0
    pages_blocked_ssrf: int = 0
    redirect_loops: int = 0
    timeouts: int = 0
    duration_ms: float = 0.0
    peak_queue_size: int = 0
    peak_active_workers: int = 0
    cancelled: bool = False
    total_timeout_exceeded: bool = False
    queue_dropped: int = 0

    def to_dict(self) -> dict:
        return {
            "seed_url": self.seed_url,
            "pages_crawled": self.pages_crawled,
            "links_found": self.links_found,
            "skipped_robots": self.skipped_robots,
            "retries": self.retries,
            "avg_response_time": round(self.avg_response_time, 2),
            "pages": [p.to_dict() for p in self.pages],
            "errors": self.errors,
            # New, backward-compatible metadata block.
            "status": self.status,
            "stats": {
                "pages_attempted": self.pages_attempted,
                "pages_succeeded": self.pages_succeeded,
                "pages_failed": self.pages_failed,
                "pages_blocked_robots": self.pages_blocked_robots,
                "pages_blocked_ssrf": self.pages_blocked_ssrf,
                "redirect_loops": self.redirect_loops,
                "timeouts": self.timeouts,
                "duration_ms": round(self.duration_ms, 2),
                "peak_queue_size": self.peak_queue_size,
                "peak_active_workers": self.peak_active_workers,
                "cancelled": self.cancelled,
                "total_timeout_exceeded": self.total_timeout_exceeded,
                "queue_dropped": self.queue_dropped,
            },
        }
