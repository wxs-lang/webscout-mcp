"""
Search Service - orchestrates multiple SearchProviders with fallback and circuit breaking.

This is the main entry point for search operations. It manages multiple
SearchProvider implementations and provides:
  - Sequential fallback (try provider 1, if fails try provider 2, etc.)
  - Circuit breaker per provider (via SearchHealthManager)
  - Health tracking and reporting
  - Result deduplication (planned)
  - Standardized error responses

This replaces the old SearchEngine class with a cleaner, more testable
architecture based on the SearchProvider interface.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from .errors import StandardErrorCode
from .logging_config import get_logger
from .provider_router import ProviderCostTier, ProviderRouter
from .search_health import SearchHealthManager
from .search_provider import (
    SearchProvider,
    SearchRequest,
    SearchResponse,
)

log = get_logger(__name__)


@dataclass
class SearchServiceConfig:
    """Configuration for the SearchService."""

    max_retries: int = 2
    circuit_failure_threshold: int = 5
    circuit_recovery_time: int = 60  # seconds
    request_timeout: float = 30.0
    max_results_per_provider: int = 10


class SearchService:
    """Orchestrates multiple SearchProviders with fallback and circuit breaking.

    Usage:
        service = SearchService(providers=[bing_provider, ddg_provider])
        response = await service.search(SearchRequest(query="hello"))
        if response.is_success:
            for result in response.results:
                print(result.title)
    """

    def __init__(
        self,
        providers: list[SearchProvider],
        config: SearchServiceConfig | None = None,
        router: ProviderRouter | None = None,
    ):
        """Initialize the SearchService.

        Args:
            providers: List of SearchProvider instances to use, in priority order.
            config: Optional configuration. Uses defaults if not provided.
            router: Optional dynamic provider router. If provided, uses
                health-based dynamic routing instead of fixed-order fallback.
        """
        if not providers:
            raise ValueError("At least one SearchProvider is required")

        self.providers = providers
        self.config = config or SearchServiceConfig()
        self.health_manager = SearchHealthManager(
            backend_names=[p.name for p in providers],
            failure_threshold=self.config.circuit_failure_threshold,
            recovery_time=self.config.circuit_recovery_time,
        )

        # Dynamic router (optional)
        self.router = router
        if self.router is not None:
            log.info("SearchService initialized with dynamic health-based routing")
        else:
            log.info("SearchService initialized with fixed-order fallback")

        # Statistics
        self.total_requests = 0
        self.total_fallbacks = 0
        self.total_errors = 0
        self.last_used_provider: str | None = None

        # Search result cache (in-memory, TTL-based)
        self._search_cache: dict[str, tuple[float, SearchResponse]] = {}
        self._cache_ttl = 300  # 5 minutes
        self.cache_hits = 0
        self.cache_misses = 0

    def _get_cache_key(self, request: SearchRequest) -> str:
        """Generate cache key from search request."""
        return f"{request.query.lower()}|{request.max_results}|{request.language}|{request.region}"

    def _get_from_cache(self, request: SearchRequest) -> SearchResponse | None:
        """Get search response from cache if available and not expired."""
        key = self._get_cache_key(request)
        if key in self._search_cache:
            timestamp, response = self._search_cache[key]
            if time.time() - timestamp < self._cache_ttl:
                self.cache_hits += 1
                log.debug(f"Cache hit for query: {request.query}")
                return response
            else:
                # Expired, remove
                del self._search_cache[key]
        self.cache_misses += 1
        return None

    def _put_in_cache(self, request: SearchRequest, response: SearchResponse) -> None:
        """Store successful search response in cache."""
        if response.is_success and len(response.results) > 0:
            key = self._get_cache_key(request)
            self._search_cache[key] = (time.time(), response)
            # Simple eviction: if cache too large, remove oldest entries
            if len(self._search_cache) > 1000:
                # Remove 100 oldest entries
                sorted_keys = sorted(self._search_cache.keys(), key=lambda k: self._search_cache[k][0])
                for k in sorted_keys[:100]:
                    del self._search_cache[k]

    def _is_provider_available(self, name: str) -> bool:
        """Check if a provider is available (circuit not open)."""
        backend = self.health_manager.get_backend(name)
        return backend is not None and backend.can_use()

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a search with fallback and circuit breaking.

        If a dynamic router is configured, uses health-based provider selection.
        Otherwise, tries providers in fixed order. Providers with open circuits
        are skipped. If all providers fail, returns a standardized error response.

        Args:
            request: The search request.

        Returns:
            SearchResponse with results or error information.
        """
        self.total_requests += 1

        # Check cache first
        cached = self._get_from_cache(request)
        if cached is not None:
            return cached

        errors: list[SearchResponse] = []
        tried_providers: list[str] = []

        # Build provider lookup map
        provider_map = {p.name: p for p in self.providers}

        while True:
            # Select next provider
            if self.router is not None:
                # Dynamic routing: select best available provider
                next_name = self.router.get_next_provider(exclude=tried_providers)
                if next_name is None:
                    break
                provider = provider_map.get(next_name)
                if provider is None:
                    tried_providers.append(next_name)
                    continue
            else:
                # Fixed order: find next untried provider
                provider = None
                for p in self.providers:
                    if p.name not in tried_providers:
                        provider = p
                        break
                if provider is None:
                    break

            tried_providers.append(provider.name)

            # Skip providers with open circuits (fixed order mode)
            if self.router is None and not self._is_provider_available(provider.name):
                errors.append(
                    SearchResponse.error(
                        query=request.query,
                        provider=provider.name,
                        error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                        error_message=f"Circuit open for {provider.name}",
                        retryable=False,
                    )
                )
                continue

            try:
                # Execute with timeout
                response = await asyncio.wait_for(
                    provider.search(request),
                    timeout=self.config.request_timeout,
                )

                if response.is_success:
                    self.health_manager.record_success(provider.name)
                    if self.router is not None:
                        self.router.record_result(provider.name, True, response.latency_ms)
                        self.router.set_circuit_closed(provider.name)
                    self.last_used_provider = provider.name
                    if len(errors) > 0:
                        self.total_fallbacks += 1
                    # Store in cache for future repeated queries
                    self._put_in_cache(request, response)
                    return response
                else:
                    # Provider returned an error response
                    self.health_manager.record_failure(
                        provider.name,
                        response.error_message or "Unknown error",
                    )
                    if self.router is not None:
                        self.router.record_result(
                            provider.name,
                            False,
                            response.latency_ms,
                            response.error_type,
                        )
                    errors.append(response)

            except asyncio.TimeoutError:
                self.health_manager.record_failure(provider.name, "Timeout")
                if self.router is not None:
                    self.router.record_result(provider.name, False, self.config.request_timeout * 1000, "timeout")
                errors.append(
                    SearchResponse.error(
                        query=request.query,
                        provider=provider.name,
                        error_type=StandardErrorCode.FETCH_TIMEOUT,
                        error_message=f"Timeout for {provider.name}",
                        retryable=True,
                    )
                )
            except Exception as e:
                self.health_manager.record_failure(provider.name, str(e))
                if self.router is not None:
                    self.router.record_result(provider.name, False, 0, "unknown")
                errors.append(
                    SearchResponse.error(
                        query=request.query,
                        provider=provider.name,
                        error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                        error_message=f"{type(e).__name__}: {e}",
                        retryable=True,
                    )
                )

        # All providers failed
        self.total_errors += 1
        return SearchResponse.error(
            query=request.query,
            provider="all",
            error_type=StandardErrorCode.SEARCH_ALL_BACKENDS_FAILED,
            error_message=f"All {len(self.providers)} providers failed",
            retryable=True,
        )

    def get_health_report(self) -> dict[str, Any]:
        """Get a comprehensive health report for all providers."""
        report = self.health_manager.get_health_report()
        report["service_statistics"] = {
            "total_requests": self.total_requests,
            "total_fallbacks": self.total_fallbacks,
            "total_errors": self.total_errors,
            "last_used_provider": self.last_used_provider,
            "fallback_rate": (self.total_fallbacks / self.total_requests if self.total_requests > 0 else 0.0),
            "error_rate": (self.total_errors / self.total_requests if self.total_requests > 0 else 0.0),
        }
        # Include dynamic router health report if configured
        if self.router is not None:
            report["dynamic_routing"] = self.router.get_health_report()
        return report

    def get_provider_health(self, name: str) -> dict[str, Any] | None:
        """Get health information for a specific provider."""
        backend = self.health_manager.get_backend(name)
        return backend.to_dict() if backend else None

    def reset_health(self) -> None:
        """Reset all health statistics and circuits."""
        self.health_manager.reset_all()
        self.total_requests = 0
        self.total_fallbacks = 0
        self.total_errors = 0
        self.last_used_provider = None

    async def close(self) -> None:
        """Close all providers and release resources."""
        for provider in self.providers:
            try:
                await provider.close()
            except Exception:
                pass  # Best effort cleanup


def create_search_service_from_config(
    config: Any,
    cache: Any | None = None,
) -> SearchService:
    """Create a SearchService from the application Config.

    This factory function creates SearchProvider instances for all enabled
    backends and wraps them in a SearchService with fallback and circuit
    breaking.

    Args:
        config: Application Config instance.
        cache: Optional cache instance (for future use).

    Returns:
        Configured SearchService instance.
    """
    from .search import BingBackend, DuckDuckGoHTMLBackend
    from .search_provider_adapter import SearchBackendAdapter

    providers: list[SearchProvider] = []

    # Bing backend (primary)
    try:
        bing = BingBackend(config)
        providers.append(SearchBackendAdapter(bing, name="bing"))
    except Exception as e:
        # Log but continue with other backends
        print(f"Warning: Could not initialize Bing backend: {e}")

    # DuckDuckGo backend (fallback)
    try:
        ddg = DuckDuckGoHTMLBackend(config)
        providers.append(SearchBackendAdapter(ddg, name="duckduckgo"))
    except Exception as e:
        print(f"Warning: Could not initialize DuckDuckGo backend: {e}")

    # Tavily API backend (stable fallback, requires TAVILY_API_KEY)
    try:
        from .tavily_provider import TavilySearchProvider

        tavily = TavilySearchProvider(config)
        if tavily.is_configured:
            providers.append(tavily)
            print("Tavily API backend initialized (stable fallback)")
        else:
            print("Tavily API key not configured, skipping Tavily backend")
    except Exception as e:
        print(f"Warning: Could not initialize Tavily backend: {e}")

    if not providers:
        raise RuntimeError("No search providers could be initialized")

    service_config = SearchServiceConfig(
        circuit_failure_threshold=getattr(config, "circuit_failure_threshold", 5),
        circuit_recovery_time=getattr(config, "circuit_recovery_time", 60),
        request_timeout=getattr(config, "search_timeout", 30.0),
    )

    # Create dynamic provider router with health-based scoring
    # Free providers (Bing, DDG) are preferred, paid providers (Tavily)
    # are used only when free providers are degraded or unavailable
    cost_tiers = {
        "bing": ProviderCostTier.FREE,
        "duckduckgo": ProviderCostTier.FREE,
        "google": ProviderCostTier.FREE,
        "brave": ProviderCostTier.FREE,
        "serpapi": ProviderCostTier.PAID,
        "tavily": ProviderCostTier.PAID,
    }
    router = ProviderRouter(
        provider_names=[p.name for p in providers],
        cost_tiers=cost_tiers,
        prefer_free=True,
        min_score_threshold=30.0,
    )

    return SearchService(providers=providers, config=service_config, router=router)
