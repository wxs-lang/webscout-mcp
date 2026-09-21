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
from .provider_router import ProviderCapability, ProviderCostTier, ProviderRouter
from .search_health import SearchHealthManager
from .search_provider import (
    SearchProvider,
    SearchRequest,
    SearchResponse,
)

log = get_logger(__name__)


class FallbackReason:
    """Deterministic reasons a SearchService moved from one provider to the next.

    These are observability labels (not a recovery executor). Distinct from
    hard transport/parser failures so we can answer *why* we fell back.
    """

    PROVIDER_ERROR = "PROVIDER_ERROR"
    EMPTY_RESULT = "EMPTY_RESULT"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_ERROR = "AUTH_ERROR"
    PARSER_FAILURE = "PARSER_FAILURE"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    UNAVAILABLE = "UNAVAILABLE"


def _fallback_reason_for_error(error_type: Any) -> str:
    """Map a StandardErrorCode to a deterministic fallback reason."""
    name = getattr(error_type, "value", str(error_type)).upper()
    if "TIMEOUT" in name:
        return FallbackReason.TIMEOUT
    if "RATE" in name or "429" in name:
        return FallbackReason.RATE_LIMITED
    if "AUTH" in name or "401" in name or "403" in name:
        return FallbackReason.AUTH_ERROR
    if "PARSER" in name:
        return FallbackReason.PARSER_FAILURE
    return FallbackReason.PROVIDER_ERROR


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

        # Jev shadow client (optional, injected from server.py). When None
        # or Noop, shadow recording is a no-op. Never affects ranking.
        self.jev_client = None
        self.jev_max_results = 10
        self.jev_max_state_chars = 6000
        self._pending_jev_tasks: set = set()

        # Statistics
        self.total_requests = 0
        self.total_fallbacks = 0
        self.total_errors = 0
        self.last_used_provider: str | None = None

        # Lightweight search-semantics observability (no query content).
        # provider -> {success, empty, error}
        self.provider_outcomes: dict[str, dict[str, int]] = {}
        # fallback reason label -> count
        self.fallback_reasons: dict[str, int] = {}

        # Search result cache (in-memory, TTL-based)
        self._search_cache: dict[str, tuple[float, SearchResponse]] = {}
        self._cache_ttl = 300  # 5 minutes
        self.cache_hits = 0
        self.cache_misses = 0

    def _get_cache_key(self, request: SearchRequest) -> str:
        """Generate a cache key that is sensitive to every request dimension
        that changes provider output.

        Two requests that differ only by safe_search / country / region /
        language / max_results MUST NOT share a cache entry. The query is
        normalized with casefold (whitespace already stripped in
        SearchRequest.__post_init__) so " python " and "python" match.
        """
        q = (request.query or "").casefold()
        return (
            f"{q}|max={request.max_results}|safe={bool(request.safe_search)}"
            f"|region={request.region}|lang={request.language}|country={request.country}"
        )

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
        empties: list[SearchResponse] = []
        tried_providers: list[str] = []
        route_trace: list[dict[str, Any]] = []

        # Build provider lookup map
        provider_map = {p.name: p for p in self.providers}

        def _record_outcome(provider: str, kind: str) -> None:
            bucket = self.provider_outcomes.setdefault(provider, {"success": 0, "empty": 0, "error": 0})
            bucket[kind] += 1

        def _record_fallback_reason(reason: str) -> None:
            self.fallback_reasons[reason] = self.fallback_reasons.get(reason, 0) + 1

        while True:
            # Select next provider
            if self.router is not None:
                # Dynamic routing: select best available provider, but ONLY
                # among providers that advertise SEARCH capability. After the
                # registry starts also owning FETCH/BROWSER providers (Phase 2),
                # this filter prevents HTTP/Crawl4AI from leaking into search.
                next_name = self.router.get_next_provider(
                    exclude=tried_providers,
                    capability=ProviderCapability.SEARCH,
                )
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
                reason = FallbackReason.CIRCUIT_OPEN
                route_trace.append({"provider": provider.name, "result": "skipped", "reason": reason})
                _record_fallback_reason(reason)
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
                    _record_outcome(provider.name, "success")
                    if self.router is not None:
                        self.router.record_result(provider.name, True, response.latency_ms)
                        self.router.set_circuit_closed(provider.name)
                    self.last_used_provider = provider.name
                    route_trace.append({"provider": provider.name, "result": "success", "count": len(response.results)})
                    # A real fallback means we tried more than one provider and
                    # used a later one (errors OR empties can both cause it).
                    if len(tried_providers) > 1:
                        self.total_fallbacks += 1
                    # Store in cache for future repeated queries.
                    # Only SUCCESS (non-empty) is cached; EMPTY/ERROR never.
                    self._put_in_cache(request, response)
                    # Attach internal route trace (additive; no secrets).
                    response.extra["route_trace"] = route_trace
                    # Jev shadow: best-effort, non-blocking, never affects
                    # ranking or result set.
                    self._fire_jev_shadow(request, response)
                    return response

                if response.is_empty:
                    # Soft miss: provider completed the search but had no
                    # results. It is NOT a hard failure: do not trip the
                    # circuit and do not count it as an error.
                    self.health_manager.record_empty(provider.name)
                    _record_outcome(provider.name, "empty")
                    route_trace.append({"provider": provider.name, "result": "empty"})
                    _record_fallback_reason(FallbackReason.EMPTY_RESULT)
                    empties.append(response)
                    continue

                # Hard error response (transport / auth / rate-limit / parser drift)
                self.health_manager.record_failure(
                    provider.name,
                    response.error_message or "Unknown error",
                )
                _record_outcome(provider.name, "error")
                if self.router is not None:
                    self.router.record_result(
                        provider.name,
                        False,
                        response.latency_ms,
                        response.error_type,
                    )
                reason = _fallback_reason_for_error(response.error_type)
                route_trace.append(
                    {
                        "provider": provider.name,
                        "result": "error",
                        "reason": reason,
                        "error_type": getattr(response.error_type, "value", None),
                    }
                )
                _record_fallback_reason(reason)
                errors.append(response)

            except asyncio.TimeoutError:
                self.health_manager.record_failure(provider.name, "Timeout")
                _record_outcome(provider.name, "error")
                if self.router is not None:
                    self.router.record_result(provider.name, False, self.config.request_timeout * 1000, "timeout")
                route_trace.append({"provider": provider.name, "result": "error", "reason": FallbackReason.TIMEOUT})
                _record_fallback_reason(FallbackReason.TIMEOUT)
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
                _record_outcome(provider.name, "error")
                if self.router is not None:
                    self.router.record_result(provider.name, False, 0, "unknown")
                reason = FallbackReason.PROVIDER_ERROR
                route_trace.append({"provider": provider.name, "result": "error", "reason": reason})
                _record_fallback_reason(reason)
                errors.append(
                    SearchResponse.error(
                        query=request.query,
                        provider=provider.name,
                        error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                        error_message=f"{type(e).__name__}: {e}",
                        retryable=True,
                    )
                )

        # No provider returned results. Distinguish ALL-EMPTY (every backend
        # completed the search but had no hits) from ALL-ERROR (every backend
        # genuinely failed). A mix where at least one backend returned EMPTY
        # also resolves to an aggregate EMPTY (the route_trace preserves the
        # hard errors).
        if empties:
            # Aggregate empty: NOT a system error.
            self.last_used_provider = "all"
            resp = SearchResponse.empty(query=request.query, provider="all")
            resp.extra["route_trace"] = route_trace
            return resp

        # All providers genuinely failed.
        self.total_errors += 1
        resp = SearchResponse.error(
            query=request.query,
            provider="all",
            error_type=StandardErrorCode.SEARCH_ALL_BACKENDS_FAILED,
            error_message=f"All {len(self.providers)} providers failed",
            retryable=True,
        )
        resp.extra["route_trace"] = route_trace
        return resp

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
            "provider_outcomes": self.provider_outcomes,
            "fallback_reasons": self.fallback_reasons,
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
        self.provider_outcomes.clear()
        self.fallback_reasons.clear()

    def _fire_jev_shadow(self, request: SearchRequest, response: SearchResponse) -> None:
        """Kick off a non-blocking Jev shadow recording for top-N results.

        Never raises; never mutates ranking or the result set.
        """
        if self.jev_client is None:
            return
        if getattr(self.jev_client, "name", "") == "noop":
            return
        if not getattr(response, "results", None):
            return
        try:
            import asyncio

            from . import jev_shadow

            task = asyncio.create_task(
                jev_shadow.maybe_record_search(
                    self.jev_client,
                    query=request.query,
                    results=response.results,
                    max_results=self.jev_max_results,
                    max_state_chars=self.jev_max_state_chars,
                )
            )
            self._pending_jev_tasks.add(task)
            task.add_done_callback(self._pending_jev_tasks.discard)
        except Exception:  # pragma: no cover
            log.debug("Jev search shadow fire failed", exc_info=True)

    async def close(self) -> None:
        """Close all providers and release resources."""
        # Best-effort flush pending Jev shadow tasks (fire-and-forget).
        if self._pending_jev_tasks:
            import asyncio

            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._pending_jev_tasks, return_exceptions=True),
                    timeout=10.0,
                )
            except (asyncio.TimeoutError, Exception):
                pass
            self._pending_jev_tasks.clear()
        jev = getattr(self, "jev_client", None)
        if jev is not None:
            try:
                await jev.aclose()
            except Exception:
                pass
        for provider in self.providers:
            try:
                await provider.close()
            except Exception:
                pass  # Best effort cleanup


def create_search_service_from_config(
    config: Any,
    cache: Any | None = None,
    registry: Any | None = None,
) -> SearchService:
    """Create a SearchService from the application Config.

    This factory function creates SearchProvider instances for all enabled
    backends and wraps them in a SearchService with fallback and circuit
    breaking. When a ProviderRegistry is supplied, all search providers are
    registered with it (capability ``SEARCH``) so the registry becomes the
    single source of truth for provider state.

    Args:
        config: Application Config instance.
        cache: Optional cache instance (for future use).
        registry: Optional ProviderRegistry to register providers with.
            If not provided, an internal registry is created.

    Returns:
        Configured SearchService instance.
    """
    from .provider_registry import ProviderRegistry
    from .provider_router import ProviderCapability
    from .search_providers import build_default_search_providers

    providers = build_default_search_providers(config)

    service_config = SearchServiceConfig(
        circuit_failure_threshold=getattr(config, "search_circuit_failure_threshold", 5),
        circuit_recovery_time=getattr(config, "search_circuit_recovery_time", 60),
        # Config exposes request_timeout (seconds). There is no standalone
        # `search_timeout`; the previous getattr("search_timeout", 30.0)
        # silently shadowed the configured request_timeout.
        request_timeout=float(getattr(config, "request_timeout", 30.0)),
    )

    # Create dynamic provider router with health-based scoring.
    # Free providers (Bing, DDG) are preferred, paid providers (Tavily)
    # are used only when free providers are degraded or unavailable.
    cost_tiers = {
        "bing": ProviderCostTier.FREE,
        "duckduckgo": ProviderCostTier.FREE,
        "google": ProviderCostTier.FREE,
        "brave": ProviderCostTier.FREE,
        "searxng": ProviderCostTier.FREE,
        "serpapi": ProviderCostTier.PAID,
        "tavily": ProviderCostTier.PAID,
    }
    capabilities = {p.name: {ProviderCapability.SEARCH} for p in providers}
    router = ProviderRouter(
        provider_names=[p.name for p in providers],
        cost_tiers=cost_tiers,
        prefer_free=True,
        min_score_threshold=30.0,
        capabilities=capabilities,
    )

    # Register all search providers with the registry (single source of truth).
    if registry is None:
        registry = ProviderRegistry(router=router)
    else:
        if registry.router is None:
            registry.router = router
    for provider in providers:
        registry.register(
            provider,
            capabilities={ProviderCapability.SEARCH},
            cost_tier=cost_tiers.get(provider.name, ProviderCostTier.FREE),
            description=f"{provider.name} search provider",
        )

    svc = SearchService(providers=providers, config=service_config, router=router)

    # Wire Jev shadow client (no-op when JEV_ENABLED=false).
    try:
        from .jev_client import make_jev_client

        svc.jev_client = make_jev_client(config)
        svc.jev_max_results = int(getattr(config, "jev_search_shadow_max_results", 10))
        svc.jev_max_state_chars = int(getattr(config, "jev_max_state_chars", 6000))
    except Exception:  # pragma: no cover
        log.debug("Jev search shadow wiring failed", exc_info=True)

    return svc
