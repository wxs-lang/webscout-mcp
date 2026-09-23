"""Adapter to make existing SearchBackend implementations compatible with SearchProvider.

This allows existing backends (Bing, DuckDuckGo, SerpAPI, etc.) to work
with the new standardized SearchProvider interface without modification.

New backends should implement SearchProvider directly.
Existing backends can be wrapped with SearchBackendAdapter.
"""

from __future__ import annotations

import time

from .errors import StandardErrorCode
from .exceptions import SearchParseError
from .search import SearchBackend
from .search_provider import (
    ProviderHealth,
    SearchFailureKind,
    SearchProvider,
    SearchRequest,
    SearchResponse,
)


class SearchBackendAdapter(SearchProvider):
    """Adapter that wraps an existing SearchBackend to implement SearchProvider.

    This allows existing backends to work with the new standardized interface
    without modification. New backends should implement SearchProvider directly.
    """

    def __init__(self, backend: SearchBackend, name: str | None = None) -> None:
        self.backend = backend
        self.name = name or backend.name
        super().__init__(config=getattr(backend, "config", None))

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute search using the wrapped backend and return standardized response."""
        start_time = time.time()

        try:
            # Call the existing backend's search method
            results = await self.backend.search(
                query=request.query,
                max_results=request.max_results,
                safe_search=request.safe_search,
                region=request.region,
            )

            latency_ms = self._measure_latency(start_time)

            # Ensure results have correct backend name
            for result in results:
                if not result.backend:
                    result.backend = self.name

            if results:
                response = SearchResponse.success(
                    query=request.query,
                    provider=self.name,
                    results=results,
                    latency_ms=latency_ms,
                )
            else:
                response = SearchResponse.empty(
                    query=request.query,
                    provider=self.name,
                    latency_ms=latency_ms,
                )

        except Exception as exc:
            latency_ms = self._measure_latency(start_time)
            error_type, failure_kind = self._classify_exception(exc)
            response = SearchResponse.error(
                query=request.query,
                provider=self.name,
                error_type=error_type,
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            response.failure_kind = failure_kind

        # Update health based on response
        self._update_health_from_response(response)

        return response

    async def health(self) -> ProviderHealth:
        """Get health status of the wrapped backend."""
        return self.get_health()

    async def close(self) -> None:
        """Close the wrapped backend."""
        if hasattr(self.backend, "close"):
            await self.backend.close()

    def _classify_exception(self, exc: Exception) -> tuple[StandardErrorCode, SearchFailureKind]:
        """Map a backend exception to (search-domain error code, failure kind).

        Parser drift (HTTP 200 but zero results parsed) is PARSER, never EMPTY.
        httpx timeout/connect/status are mapped to search-domain codes.
        """
        # Typed parser failure first.
        if isinstance(exc, SearchParseError):
            return StandardErrorCode.CONTENT_PARSE_ERROR, SearchFailureKind.PARSER

        # httpx transport / status errors (direct or chained via SearchError).
        cause = exc
        while cause is not None:
            try:
                import httpx

                if isinstance(cause, httpx.TimeoutException):
                    return StandardErrorCode.SEARCH_TIMEOUT, SearchFailureKind.TIMEOUT
                if isinstance(cause, httpx.ConnectError):
                    return StandardErrorCode.FETCH_CONNECTION_ERROR, SearchFailureKind.NETWORK
                if isinstance(cause, httpx.HTTPStatusError):
                    sc = cause.response.status_code
                    if sc == 429:
                        return StandardErrorCode.SEARCH_RATE_LIMITED, SearchFailureKind.RATE_LIMITED
                    if sc in (401, 403):
                        return StandardErrorCode.FETCH_FORBIDDEN, SearchFailureKind.AUTH
                    if 500 <= sc < 600:
                        return StandardErrorCode.FETCH_SERVER_ERROR, SearchFailureKind.SERVER
                    return StandardErrorCode.SEARCH_BACKEND_FAILED, SearchFailureKind.PROVIDER
            except ImportError:
                pass
            cause = getattr(cause, "__cause__", None)

        # Generic backend failure.
        return StandardErrorCode.SEARCH_BACKEND_FAILED, SearchFailureKind.PROVIDER


def adapt_backend(backend: SearchBackend, name: str | None = None) -> SearchProvider:
    """Convenience function to adapt an existing SearchBackend to SearchProvider.

    Args:
        backend: Existing SearchBackend instance
        name: Optional provider name override

    Returns:
        SearchProvider-compatible adapter
    """
    return SearchBackendAdapter(backend, name=name)
