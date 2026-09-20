"""Fetch Provider abstraction for webscout-mcp.

Defines a standardized FetchProvider interface (analogous to SearchProvider)
so that HTTP fetching, browser-based fetching, and future backends can be
registered with the ProviderRegistry and selected by the dynamic router via
the ``fetch`` / ``browser`` capabilities.

This layer is intentionally thin: it wraps the existing ``Fetcher`` (which
owns caching, rate limiting, retries, content extraction) rather than
reimplementing any of that logic.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import StandardErrorCode
from .logging_config import get_logger
from .search_provider import ProviderHealth, ProviderHealthStatus

log = get_logger(__name__)


class FetchStatus(str, Enum):
    """Status of a fetch operation."""

    SUCCESS = "success"
    ERROR = "error"


@dataclass
class FetchRequest:
    """Standardized fetch request.

    Mirrors the parameters of ``Fetcher.fetch`` so any FetchProvider can
    receive the same request shape regardless of backend.
    """

    url: str
    extract: bool = True
    output_format: str | None = None
    max_chars: int | None = None
    bypass_cache: bool = False
    start_char: int = 0
    timeout: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.url = self.url.strip()


@dataclass
class FetchResponse:
    """Standardized fetch response.

    Carries the same fields as ``FetchResult`` plus provider attribution,
    latency and a standard error code so agents can interpret failures
    uniformly (same contract as SearchResponse).
    """

    url: str
    final_url: str
    status_code: int
    provider: str
    title: str = ""
    content: str = ""
    content_type: str = ""
    extracted: bool = False
    cached: bool = False
    error: str | None = None
    latency_ms: float = 0.0
    error_code: StandardErrorCode | None = None
    retryable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    # Internal-only: raw decoded HTML used by escalation heuristics.
    # Never serialized to to_dict(), metadata, WebResult, logs, or SQLite.
    raw_html: str = ""

    @property
    def is_success(self) -> bool:
        return self.error is None and self.status_code < 400

    @property
    def is_error(self) -> bool:
        return self.error is not None or self.status_code >= 400

    @classmethod
    def from_fetch_result(cls, result: Any, provider: str, latency_ms: float) -> FetchResponse:
        """Build a FetchResponse from an existing FetchResult.

        Keeps a single source of truth for fetch output: the existing
        ``Fetcher`` produces ``FetchResult``; this converts it to the
        standardized provider response without duplicating logic.
        """
        error = getattr(result, "error", None)
        status_code = getattr(result, "status_code", 0)
        error_code = None
        retryable = False
        if error is not None or status_code >= 400:
            error_code, retryable = _map_fetch_error(status_code, error)
        return cls(
            url=getattr(result, "url", ""),
            final_url=getattr(result, "final_url", "") or getattr(result, "url", ""),
            status_code=status_code,
            provider=provider,
            title=getattr(result, "title", ""),
            content=getattr(result, "content", ""),
            content_type=getattr(result, "content_type", ""),
            extracted=getattr(result, "extracted", False),
            cached=getattr(result, "cached", False),
            error=error,
            latency_ms=latency_ms,
            error_code=error_code,
            retryable=retryable,
            metadata=dict(getattr(result, "metadata", {}) or {}),
            raw_html=getattr(result, "raw_html", "") or "",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "provider": self.provider,
            "title": self.title,
            "content": self.content,
            "content_type": self.content_type,
            "extracted": self.extracted,
            "cached": self.cached,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 2),
            "error_code": self.error_code.value if self.error_code else None,
            "retryable": self.retryable,
        }


def _map_fetch_error(status_code: int, error: str | None) -> tuple[StandardErrorCode | None, bool]:
    """Map HTTP status / exception text to a standard error code."""
    if status_code == 403:
        return StandardErrorCode.FETCH_FORBIDDEN, False
    if status_code == 429:
        return StandardErrorCode.FETCH_RATE_LIMITED, True
    if status_code in (408, 504) or (error and "timeout" in error.lower()):
        return StandardErrorCode.FETCH_TIMEOUT, True
    if status_code >= 500:
        return StandardErrorCode.FETCH_SERVER_ERROR, True
    if status_code >= 400:
        return StandardErrorCode.FETCH_FAILED, False
    if error is not None:
        if "dns" in error.lower():
            return StandardErrorCode.FETCH_DNS_ERROR, True
        if "connect" in error.lower():
            return StandardErrorCode.FETCH_CONNECTION_ERROR, True
        if "ssl" in error.lower() or "certificate" in error.lower():
            return StandardErrorCode.FETCH_SSL_ERROR, True
        if "robot" in error.lower():
            return StandardErrorCode.FETCH_ROBOTS_DENIED, False
        if "too large" in error.lower():
            return StandardErrorCode.FETCH_CONTENT_TOO_LARGE, False
        return StandardErrorCode.FETCH_FAILED, True
    return None, False


class FetchProvider(ABC):
    """Abstract base class for all fetch providers.

    Implementations wrap a real fetching backend (HTTP client, browser, ...)
    and return a standardized FetchResponse. Health reporting follows the
    same convention as SearchProvider (ProviderHealth).
    """

    name: str = "base"

    def __init__(self, config: Any) -> None:
        self.config = config
        self._health = ProviderHealth(provider=self.name)

    @abstractmethod
    async def fetch(self, request: FetchRequest) -> FetchResponse:
        """Fetch a URL and return a standardized response.

        Args:
            request: Standardized fetch request.

        Returns:
            Standardized fetch response.
        """
        raise NotImplementedError

    @abstractmethod
    async def health(self) -> ProviderHealth:
        """Get the current health status of the provider."""
        raise NotImplementedError

    async def close(self) -> None:
        """Close any resources held by the provider."""

    def get_health(self) -> ProviderHealth:
        """Get the cached health status."""
        return self._health

    def _measure_latency(self, start_time: float) -> float:
        return (time.time() - start_time) * 1000

    def _update_health_from_response(self, response: FetchResponse) -> None:
        """Update provider health based on a fetch response."""
        self._health.latency_ms = response.latency_ms
        self._health.last_check = time.time()
        if response.is_success:
            self._health.status = ProviderHealthStatus.HEALTHY
            self._health.error_count = 0
            self._health.last_error = None
        else:
            self._health.error_count += 1
            self._health.last_error = response.error or f"HTTP {response.status_code}"
            self._health.status = (
                ProviderHealthStatus.UNHEALTHY if self._health.error_count >= 5 else ProviderHealthStatus.DEGRADED
            )


class HTTPFetchProvider(FetchProvider):
    """FetchProvider backed by the existing smart ``Fetcher``.

    Reuses Fetcher's caching, rate limiting, retry/backoff and content
    extraction — no logic is duplicated here.
    """

    name = "http"

    def __init__(self, fetcher: Any):
        """Initialize with an existing Fetcher instance.

        Args:
            fetcher: A ``webscout_mcp.fetcher.Fetcher`` instance.
        """
        super().__init__(getattr(fetcher, "config", None))
        self.fetcher = fetcher
        self.name = "http"

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        """Fetch via the wrapped Fetcher."""
        start = time.time()
        try:
            result = await self.fetcher.fetch(
                url=request.url,
                extract=request.extract,
                output_format=request.output_format,
                max_chars=request.max_chars,
                bypass_cache=request.bypass_cache,
                start_char=request.start_char,
            )
            latency_ms = self._measure_latency(start)
            response = FetchResponse.from_fetch_result(result, provider=self.name, latency_ms=latency_ms)
            self._update_health_from_response(response)
            return response
        except Exception as exc:  # pragma: no cover - defensive
            latency_ms = self._measure_latency(start)
            code, retryable = _map_fetch_error(0, str(exc))
            response = FetchResponse(
                url=request.url,
                final_url=request.url,
                status_code=0,
                provider=self.name,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=latency_ms,
                error_code=code,
                retryable=retryable,
            )
            self._update_health_from_response(response)
            return response

    async def health(self) -> ProviderHealth:
        """Health from the wrapped Fetcher's stats."""
        try:
            stats = self.fetcher.get_stats()
            total = stats.get("total_requests", 0)
            if total > 0:
                success_rate = stats.get("success_rate", 0.0)
                self._health.success_rate = success_rate
                self._health.status = (
                    ProviderHealthStatus.HEALTHY if success_rate >= 0.9 else ProviderHealthStatus.DEGRADED
                )
                self._health.latency_ms = stats.get("average_response_time", 0.0) * 1000
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Could not read fetcher stats: %s", exc)
        return self._health

    async def close(self) -> None:
        """Close the wrapped Fetcher."""
        await self.fetcher.close()

    def get_stats(self) -> dict[str, Any]:
        """Expose the wrapped Fetcher's statistics."""
        return dict(self.fetcher.get_stats() or {})


class BrowserFetchProvider(FetchProvider):
    """FetchProvider abstraction for browser-based fetching.

    This is a structural placeholder for the browser capability: it defines
    the interface (and defaults to disabled) but does NOT pull in any real
    browser automation dependency (Playwright / Crawl4AI / Browser Use).
    Concrete browser backends can extend this class in a future iteration.

    Note:
        The provider is registered as unavailable until a real backend is
        wired in, so the router will never select it by accident.
    """

    name = "browser"

    def __init__(self, config: Any | None = None) -> None:
        super().__init__(config)
        self._health = ProviderHealth(
            provider=self.name,
            status=ProviderHealthStatus.UNKNOWN,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        """Browser fetching is not implemented in this release.

        Raises:
            NotImplementedError: Always — browser backend is an abstraction
                placeholder until a real automation dependency is integrated.
        """
        raise NotImplementedError(
            "BrowserFetchProvider is an abstraction placeholder; "
            "no browser automation backend is wired in this release."
        )

    async def health(self) -> ProviderHealth:
        """Report UNKNOWN (not available until a backend is wired in)."""
        return self._health
