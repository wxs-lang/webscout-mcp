"""SearXNG Search provider.

SearXNG is a self-hosted, privacy-respecting metasearch engine that aggregates
results from many search backends (Google, Bing, DuckDuckGo, Brave, etc.).
It exposes a simple JSON API at ``{base_url}/search?format=json`` and requires
no API key when you run your own instance.

Configuration (environment variables):
    SEARXNG_BASE_URL   e.g. https://searx.be  (or your self-hosted instance)
    SEARXNG_TIMEOUT    request timeout in seconds (default 15.0)

This provider is registered as a FREE-tier fallback after Bing/DuckDuckGo and
before Tavily. The dynamic router will prefer it once it proves healthy; if
the instance is down, it short-circuits and existing providers take over.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .errors import StandardErrorCode
from .logging_config import get_logger
from .search import SearchResult
from .search_provider import (
    ProviderHealth,
    SearchProvider,
    SearchRequest,
    SearchResponse,
    SearchStatus,
)

log = get_logger(__name__)

DEFAULT_TIMEOUT = 15.0
MAX_RESULTS_CAP = 20


class SearXNGSearchProvider(SearchProvider):
    """SearXNG metasearch provider.

    Talks to a SearXNG instance's JSON API. No API key required for a
    self-hosted instance; some public instances disable the JSON format, in
    which case this provider reports an error and the router falls through.
    """

    name: str = "searxng"

    def __init__(self, config: Any, base_url: str | None = None) -> None:
        super().__init__(config)
        self.base_url = (base_url or getattr(config, "searxng_base_url", "") or "").rstrip("/")
        self.timeout = float(getattr(config, "searxng_timeout", DEFAULT_TIMEOUT))
        self._health = ProviderHealth(provider=self.name)
        self._client: httpx.AsyncClient | None = None

    @property
    def is_configured(self) -> bool:
        """A SearXNG instance is usable as soon as a base URL is set."""
        return bool(self.base_url)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "User-Agent": "webscout-mcp/1.2",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def search(self, request: SearchRequest) -> SearchResponse:
        start_time = time.time()

        if not self.is_configured:
            return SearchResponse.error(
                query=request.query,
                provider=self.name,
                error_type=StandardErrorCode.SYSTEM_CONFIG_ERROR,
                error_message="SEARXNG_BASE_URL not set",
                latency_ms=self._measure_latency(start_time),
            )

        try:
            client = await self._get_client()
            params: dict[str, Any] = {
                "q": request.query,
                "format": "json",
                "pageno": 1,
            }
            # SearXNG uses 'language' (e.g. 'en', 'zh') rather than region codes.
            if request.language:
                params["language"] = request.language
            if request.safe_search:
                params["safesearch"] = 1
            params["categories"] = "general"

            resp = await client.get(f"{self.base_url}/search", params=params)

            if resp.status_code == 429:
                return SearchResponse.error(
                    query=request.query,
                    provider=self.name,
                    error_type=StandardErrorCode.SEARCH_RATE_LIMITED,
                    error_message="SearXNG rate limited",
                    latency_ms=self._measure_latency(start_time),
                    retryable=True,
                )
            if resp.status_code == 403:
                # Public instances often 403 the JSON format without a browser UA.
                # Classified as a backend failure; the router circuit-breaker
                # will stop retrying after repeated 403s.
                return SearchResponse.error(
                    query=request.query,
                    provider=self.name,
                    error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                    error_message="SearXNG denied JSON API access (403); enable formats on your instance",
                    latency_ms=self._measure_latency(start_time),
                )
            if resp.status_code >= 500:
                return SearchResponse.error(
                    query=request.query,
                    provider=self.name,
                    error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                    error_message=f"SearXNG server error: {resp.status_code}",
                    latency_ms=self._measure_latency(start_time),
                    retryable=True,
                )
            resp.raise_for_status()
            data = resp.json()

            results: list[SearchResult] = []
            for idx, item in enumerate(data.get("results", [])):
                if idx >= min(request.max_results, MAX_RESULTS_CAP):
                    break
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", ""),
                        position=idx + 1,
                        backend=self.name,
                    )
                )

            response = SearchResponse(
                query=request.query,
                provider=self.name,
                status=SearchStatus.SUCCESS if results else SearchStatus.EMPTY,
                results=results,
                latency_ms=self._measure_latency(start_time),
            )
            self._update_health_from_response(response)
            return response

        except httpx.TimeoutException:
            return SearchResponse.error(
                query=request.query,
                provider=self.name,
                error_type=StandardErrorCode.SEARCH_TIMEOUT,
                error_message=f"SearXNG timed out after {self.timeout}s",
                latency_ms=self._measure_latency(start_time),
                retryable=True,
            )
        except httpx.ConnectError:
            return SearchResponse.error(
                query=request.query,
                provider=self.name,
                error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                error_message="Could not connect to SearXNG instance",
                latency_ms=self._measure_latency(start_time),
                retryable=True,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("SearXNG search error")
            return SearchResponse.error(
                query=request.query,
                provider=self.name,
                error_type=StandardErrorCode.SYSTEM_ERROR,
                error_message=str(e),
                latency_ms=self._measure_latency(start_time),
                retryable=True,
            )

    async def health(self) -> ProviderHealth:
        return self._health

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
