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
    SearchFailureKind,
    SearchProvider,
    SearchRequest,
    SearchResponse,
)
from .search_recovery import (
    SearchRecoveryAction,
    SearchRecoveryDecision,
    SearchRecoveryReason,
    classify_circuit_open,
    classify_search_final_outcome,
    classify_search_recovery,
    classify_unavailable,
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
    """DEPRECATED: kept for backward-compatible references only.

    Phase 3 production fallback reasons come directly from
    ``SearchRecoveryDecision.reason.value``. This function must not be used
    as an authoritative mapping in the search loop.
    """
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


def _router_error_label(reason: SearchRecoveryReason) -> str:
    """Map a recovery reason to the ProviderRouter error taxonomy.

    Used ONLY for Router ranking metrics (error_429 / error_403 /
    error_timeout / error_connection / error_other). The Router label never
    feeds back into SearchRecovery.
    """
    if reason == SearchRecoveryReason.RATE_LIMITED:
        return "rate_limited"
    if reason == SearchRecoveryReason.AUTH_ERROR:
        return "forbidden"
    if reason == SearchRecoveryReason.TIMEOUT:
        return "timeout"
    if reason == SearchRecoveryReason.NETWORK_FAILURE:
        return "connection_error"
    return "other"


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
        # recovery classifier observability
        self.recovery_reasons: dict[str, int] = {}
        self.recovery_actions: dict[str, int] = {}
        # DEPRECATED: Phase 2 recorded unconditional "agree"; Phase 3 production
        # is driven by the decision itself, so this metric is no longer
        # meaningful. Kept as a zeroed field for backward-compatible reports.
        self.recovery_agreement: dict[str, int] = {"agree": 0, "disagree": 0}
        # Phase 3: actual execution outcomes keyed by action -> outcome -> count.
        self.recovery_execution: dict[str, dict[str, int]] = {}

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
        """Execute a search driven by SearchRecoveryDecision (Phase 3).

        Production flow:
            candidate -> provider outcome -> classify_search_recovery()
            -> SearchRecoveryDecision -> execute(action)
        The decision is the single source of truth: there is no parallel
        if/else routing. Each provider is called at most once per request.
        """
        _decision_started_at = time.time()
        self.total_requests += 1

        # Cache hit is the shortest path: 0 provider HTTP, 0 recovery, 0 Jev.
        cached = self._get_from_cache(request)
        if cached is not None:
            try:
                from .decision_adapter import record_search_decision

                record_search_decision(
                    request=request,
                    response=cached,
                    final_decision=None,
                    provider_attempt_count=0,
                    fallback_count=0,
                    cache_hit=True,
                    started_at=_decision_started_at,
                )
            except Exception:  # pragma: no cover
                log.debug("search cache-hit telemetry failed", exc_info=True)
            return cached

        tried_providers: list[str] = []
        route_trace: list[dict[str, Any]] = []
        outcome_decisions: list[SearchRecoveryDecision] = []
        provider_map = {p.name: p for p in self.providers}

        def _record_outcome(provider: str, kind: str) -> None:
            bucket = self.provider_outcomes.setdefault(provider, {"success": 0, "empty": 0, "error": 0})
            bucket[kind] += 1

        def _record_recovery(decision: SearchRecoveryDecision) -> None:
            outcome_decisions.append(decision)
            self.recovery_reasons[decision.reason.value] = self.recovery_reasons.get(decision.reason.value, 0) + 1
            self.recovery_actions[decision.action.value] = self.recovery_actions.get(decision.action.value, 0) + 1

        def _record_execution(action: SearchRecoveryAction, outcome: str) -> None:
            bucket = self.recovery_execution.setdefault(action.value, {})
            bucket[outcome] = bucket.get(outcome, 0) + 1

        def _emit_decision(resp: SearchResponse, decision: SearchRecoveryDecision | None) -> None:
            """Best-effort DecisionEvent recording. Never affects production."""
            try:
                from .decision_adapter import record_search_decision

                circuit_skips = sum(1 for e in route_trace if e.get("execution_outcome") == "circuit_skipped")
                unavailable_skips = sum(1 for e in route_trace if e.get("execution_outcome") == "unavailable_skipped")
                record_search_decision(
                    request=request,
                    response=resp,
                    final_decision=decision,
                    provider_attempt_count=len(tried_providers),
                    fallback_count=max(0, len(tried_providers) - 1),
                    circuit_skips=circuit_skips,
                    unavailable_skips=unavailable_skips,
                    started_at=_decision_started_at,
                )
            except Exception:  # pragma: no cover
                log.debug("search decision telemetry failed", exc_info=True)

        def _next_candidate() -> tuple[str | None, Any | None, str | None]:
            """Return (name, provider_or_None, skip_reason_or_None).

            skip_reason in {None, "circuit_open", "unavailable"}.
            SearchHealthManager.can_use() is the sole availability authority.
            """
            if self.router is not None:
                ranked = self.router.get_ranked_providers(capability=ProviderCapability.SEARCH)
                for score in ranked:
                    name = score.name
                    if name in tried_providers:
                        continue
                    if name not in provider_map:
                        return name, None, "unavailable"
                    if not self._is_provider_available(name):
                        return name, None, "circuit_open"
                    return name, provider_map[name], None
                return None, None, None
            for p in self.providers:
                if p.name in tried_providers:
                    continue
                if not self._is_provider_available(p.name):
                    return p.name, None, "circuit_open"
                return p.name, p, None
            return None, None, None

        def _apply_health(provider_name: str, decision: SearchRecoveryDecision, latency_ms: float) -> None:
            """Mutate SearchHealthManager + Router metrics according to reason.

            INVALID_QUERY is request-level: it must NOT pollute provider health.
            EMPTY is neutral: no Router success/error, no circuit.
            """
            reason = decision.reason
            if reason == SearchRecoveryReason.INVALID_QUERY:
                return
            if reason == SearchRecoveryReason.RESULT_AVAILABLE:
                self.health_manager.record_success(provider_name)
                _record_outcome(provider_name, "success")
                if self.router is not None:
                    self.router.record_result(provider_name, True, latency_ms)
                return
            if reason == SearchRecoveryReason.EMPTY_RESULT:
                self.health_manager.record_empty(provider_name)
                _record_outcome(provider_name, "empty")
                # EMPTY is neutral for Router: neither success nor error.
                return
            if reason in (SearchRecoveryReason.CIRCUIT_OPEN, SearchRecoveryReason.UNAVAILABLE):
                # No real provider call; no health mutation.
                return
            # All hard-failure reasons: record provider failure.
            self.health_manager.record_failure(provider_name, reason.value)
            _record_outcome(provider_name, "error")
            if self.router is not None:
                self.router.record_result(provider_name, False, latency_ms, _router_error_label(reason))

        # Empty / whitespace query is a request-level STOP: 0 provider network,
        # 0 health/circuit mutation, 0 Jev. Goes through the same Decision path.
        if not request.query:
            invalid_resp = SearchResponse.error(
                query=request.query,
                provider="request",
                error_type=StandardErrorCode.SEARCH_INVALID_QUERY,
                error_message="Search query must not be empty",
                retryable=False,
                failure_kind=SearchFailureKind.INVALID_REQUEST,
            )
            decision = classify_search_recovery(invalid_resp)
            _record_recovery(decision)
            _record_execution(decision.action, "stopped")
            route_trace.append(
                {
                    "stage": "request_validation",
                    "result": "error",
                    "recovery_reason": decision.reason.value,
                    "recommended_action": decision.action.value,
                    "execution_outcome": "stopped",
                }
            )
            invalid_resp.extra["route_trace"] = route_trace
            invalid_resp.extra["recovery_reason"] = decision.reason.value
            _emit_decision(invalid_resp, decision)
            return invalid_resp

        final_decision: SearchRecoveryDecision | None = None

        while True:
            name, provider, skip_reason = _next_candidate()
            if name is None:
                break
            tried_providers.append(name)

            # --- skipped candidates (0 network) ---
            if skip_reason == "circuit_open":
                decision = classify_circuit_open()
                _record_recovery(decision)
                _record_execution(decision.action, "circuit_skipped")
                self.fallback_reasons[decision.reason.value] = self.fallback_reasons.get(decision.reason.value, 0) + 1
                route_trace.append(
                    {
                        "provider": name,
                        "result": "skipped",
                        "reason": decision.reason.value,
                        "recovery_reason": decision.reason.value,
                        "recommended_action": decision.action.value,
                        "execution_outcome": "circuit_skipped",
                    }
                )
                continue
            if skip_reason == "unavailable":
                decision = classify_unavailable()
                _record_recovery(decision)
                _record_execution(decision.action, "unavailable_skipped")
                self.fallback_reasons[decision.reason.value] = self.fallback_reasons.get(decision.reason.value, 0) + 1
                route_trace.append(
                    {
                        "provider": name,
                        "result": "skipped",
                        "reason": decision.reason.value,
                        "recovery_reason": decision.reason.value,
                        "recommended_action": decision.action.value,
                        "execution_outcome": "unavailable_skipped",
                    }
                )
                continue

            # --- real provider call (at most once per provider per request) ---
            if provider is None:
                # Defensive: should not happen because skip_reason handles it.
                continue
            try:
                response = await asyncio.wait_for(
                    provider.search(request),
                    timeout=self.config.request_timeout,
                )
            except asyncio.TimeoutError:
                response = SearchResponse.error(
                    query=request.query,
                    provider=name,
                    error_type=StandardErrorCode.SEARCH_TIMEOUT,
                    error_message=f"Timeout for {name}",
                    retryable=True,
                    failure_kind=SearchFailureKind.TIMEOUT,
                )
            except Exception as e:  # noqa: BLE001
                response = SearchResponse.error(
                    query=request.query,
                    provider=name,
                    error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
                    error_message=f"{type(e).__name__}: {e}",
                    retryable=True,
                    failure_kind=SearchFailureKind.PROVIDER,
                )

            # --- classify ONCE, then execute ---
            decision = classify_search_recovery(response)
            _record_recovery(decision)
            _apply_health(name, decision, response.latency_ms)
            # fallback_reasons only records why we LEFT a candidate / moved to
            # the next provider. ACCEPT and STOP are not "fallbacks".

            if decision.action == SearchRecoveryAction.ACCEPT:
                # RESULT_AVAILABLE only.
                self.last_used_provider = name
                if len(tried_providers) > 1:
                    self.total_fallbacks += 1
                _record_execution(decision.action, "accepted")
                route_trace.append(
                    {
                        "provider": name,
                        "result": "success",
                        "count": len(response.results),
                        "recovery_reason": decision.reason.value,
                        "recommended_action": decision.action.value,
                        "execution_outcome": "accepted",
                    }
                )
                self._put_in_cache(request, response)
                response.extra["route_trace"] = route_trace
                self._fire_jev_shadow(request, response)
                _emit_decision(response, decision)
                return response

            if decision.action == SearchRecoveryAction.STOP:
                # Request-level failure (e.g. INVALID_QUERY): stop immediately,
                # do not pollute provider health, do not try other providers.
                # Save this decision as the final one so it is recorded exactly
                # once (no re-classification in the finalizer).
                final_decision = decision
                _record_execution(decision.action, "stopped")
                route_trace.append(
                    {
                        "provider": name,
                        "result": "error",
                        "reason": decision.reason.value,
                        "recovery_reason": decision.reason.value,
                        "recommended_action": decision.action.value,
                        "execution_outcome": "stopped",
                    }
                )
                break

            # TRY_NEXT_PROVIDER or NONE: move to the next eligible provider.
            # This is the only provider-level path that counts as a fallback.
            self.fallback_reasons[decision.reason.value] = self.fallback_reasons.get(decision.reason.value, 0) + 1
            outcome = (
                "next_provider" if decision.action == SearchRecoveryAction.TRY_NEXT_PROVIDER else "no_action_continue"
            )
            _record_execution(decision.action, outcome)
            route_trace.append(
                {
                    "provider": name,
                    "result": "empty" if response.is_empty else "error",
                    "reason": decision.reason.value,
                    "error_type": getattr(response.error_type, "value", None),
                    "failure_kind": getattr(response.failure_kind, "value", None),
                    "recovery_reason": decision.reason.value,
                    "recommended_action": decision.action.value,
                    "execution_outcome": outcome,
                }
            )
            continue

        # --- finalizer drives production outcome ---
        if final_decision is None:
            final_decision = classify_search_final_outcome(outcome_decisions)
            _record_recovery(final_decision)
        # If final_decision was set by a provider STOP, it was already recorded
        # in the loop; do not record a second time.

        if final_decision.action == SearchRecoveryAction.RETURN_EMPTY:
            self.last_used_provider = "all"
            _record_execution(final_decision.action, "returned_empty")
            resp = SearchResponse.empty(query=request.query, provider="all")
            resp.extra["route_trace"] = route_trace
            resp.extra["recovery_reason"] = final_decision.reason.value
            _emit_decision(resp, final_decision)
            return resp

        if final_decision.action == SearchRecoveryAction.STOP:
            # Provider-level STOP was already recorded in the loop. This block
            # only assembles the final response; no second execution count.
            self.last_used_provider = "all"
            resp = SearchResponse.error(
                query=request.query,
                provider="all",
                error_type=StandardErrorCode.SEARCH_INVALID_QUERY,
                error_message="Invalid search query",
                retryable=False,
            )
            resp.extra["route_trace"] = route_trace
            resp.extra["recovery_reason"] = final_decision.reason.value
            _emit_decision(resp, final_decision)
            return resp

        # RETURN_ERROR (ALL_FAILED)
        self.total_errors += 1
        self.last_used_provider = "all"
        _record_execution(final_decision.action, "returned_error")
        resp = SearchResponse.error(
            query=request.query,
            provider="all",
            error_type=StandardErrorCode.SEARCH_ALL_BACKENDS_FAILED,
            error_message=f"All {len(self.providers)} providers failed",
            retryable=True,
        )
        resp.extra["route_trace"] = route_trace
        resp.extra["recovery_reason"] = final_decision.reason.value
        _emit_decision(resp, final_decision)
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
            "recovery_reasons": self.recovery_reasons,
            "recovery_actions": self.recovery_actions,
            "recovery_execution": self.recovery_execution,
            "recovery_agreement": self.recovery_agreement,
            "recovery_agreement_deprecated": True,
            "search_circuit_authority": "SearchHealthManager",
            "effective_search_availability": {
                name: {
                    "available": self.health_manager.get_backend(name).can_use(),
                    "circuit_open": self.health_manager.get_backend(name).circuit_open,
                }
                for name in (p.name for p in self.providers)
                if self.health_manager.get_backend(name) is not None
            },
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
        self.recovery_reasons.clear()
        self.recovery_actions.clear()
        self.recovery_execution.clear()
        self.recovery_agreement = {"agree": 0, "disagree": 0}

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
