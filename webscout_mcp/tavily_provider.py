"""Tavily Search API provider.

Tavily is a search API designed specifically for AI agents.
It provides stable, structured search results with no HTML scraping.
This serves as a reliable fallback when free HTML-based search backends fail.

Get a free API key at: https://tavily.com/
Set via environment variable: TAVILY_API_KEY
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .logging_config import get_logger
from .search import SearchResult
from .search_provider import (
    ProviderHealth,
    ProviderHealthStatus,
    SearchRequest,
    SearchResponse,
    SearchStatus,
)

log = get_logger(__name__)

TAVILY_API_URL = "https://api.tavily.com/search"
DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_RESULTS = 10


class TavilySearchProvider:
    """Tavily Search API provider.

    Provides stable, API-based search as a reliable fallback.
    Requires TAVILY_API_KEY environment variable.
    """

    name: str = "tavily"

    def __init__(self, config: Any, api_key: str | None = None) -> None:
        self.config = config
        self.api_key = api_key or getattr(config, "tavily_api_key", None)
        self.timeout = getattr(config, "tavily_timeout", DEFAULT_TIMEOUT)
        self._health = ProviderHealth(provider=self.name)
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """Check if Tavily API key is configured."""
        return bool(self.api_key)

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create httpx async client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "User-Agent": "webscout-mcp/1.0",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Perform search via Tavily API.

        Args:
            request: Standardized search request

        Returns:
            Standardized search response
        """
        start_time = time.time()

        if not self.is_configured:
            log.warning("Tavily API key not configured, skipping")
            return SearchResponse(
                query=request.query,
                provider=self.name,
                status=SearchStatus.ERROR,
                error_type="not_configured",
                error_message="TAVILY_API_KEY not set",
                retryable=False,
                latency_ms=self._measure_latency(start_time),
            )

        try:
            client = await self._get_client()

            payload = {
                "api_key": self.api_key,
                "query": request.query,
                "search_depth": "basic",
                "max_results": min(request.max_results, DEFAULT_MAX_RESULTS),
                "include_answer": False,
                "include_raw_content": False,
            }

            # Add region/language if specified
            if request.region and request.region != "wt-wt":
                parts = request.region.split("-")
                if len(parts) == 2:
                    payload["include_domains"] = []  # Tavily doesn't have direct region param

            response = await client.post(
                TAVILY_API_URL,
                json=payload,
            )

            if response.status_code == 401:
                return SearchResponse(
                    query=request.query,
                    provider=self.name,
                    status=SearchStatus.ERROR,
                    error_type="auth_error",
                    error_message="Invalid Tavily API key",
                    retryable=False,
                    latency_ms=self._measure_latency(start_time),
                )

            if response.status_code == 429:
                return SearchResponse(
                    query=request.query,
                    provider=self.name,
                    status=SearchStatus.ERROR,
                    error_type="rate_limited",
                    error_message="Tavily API rate limit exceeded",
                    retryable=True,
                    latency_ms=self._measure_latency(start_time),
                )

            if response.status_code >= 500:
                return SearchResponse(
                    query=request.query,
                    provider=self.name,
                    status=SearchStatus.ERROR,
                    error_type="server_error",
                    error_message=f"Tavily API server error: {response.status_code}",
                    retryable=True,
                    latency_ms=self._measure_latency(start_time),
                )

            response.raise_for_status()
            data = response.json()

            # Parse Tavily results
            results: list[SearchResult] = []
            tavily_results = data.get("results", [])

            for idx, item in enumerate(tavily_results):
                result = SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    position=idx + 1,
                    backend=self.name,
                    relevance_score=item.get("score", 0.0),
                )
                results.append(result)

            search_response = SearchResponse(
                query=request.query,
                provider=self.name,
                status=SearchStatus.SUCCESS if results else SearchStatus.EMPTY,
                results=results,
                latency_ms=self._measure_latency(start_time),
            )

            self._update_health_from_response(search_response)
            return search_response

        except httpx.TimeoutException:
            return SearchResponse(
                query=request.query,
                provider=self.name,
                status=SearchStatus.ERROR,
                error_type="timeout",
                error_message=f"Tavily API timed out after {self.timeout}s",
                retryable=True,
                latency_ms=self._measure_latency(start_time),
            )
        except httpx.ConnectError:
            return SearchResponse(
                query=request.query,
                provider=self.name,
                status=SearchStatus.ERROR,
                error_type="connection_error",
                error_message="Could not connect to Tavily API",
                retryable=True,
                latency_ms=self._measure_latency(start_time),
            )
        except Exception as e:
            log.error(f"Tavily search error: {e}", exc_info=True)
            return SearchResponse(
                query=request.query,
                provider=self.name,
                status=SearchStatus.ERROR,
                error_type="unknown_error",
                error_message=str(e),
                retryable=True,
                latency_ms=self._measure_latency(start_time),
            )

    async def health(self) -> ProviderHealth:
        """Get current health status."""
        return self._health

    async def close(self) -> None:
        """Close httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _measure_latency(self, start_time: float) -> float:
        return (time.time() - start_time) * 1000

    def _update_health_from_response(self, response: SearchResponse) -> None:
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
        return self._health
