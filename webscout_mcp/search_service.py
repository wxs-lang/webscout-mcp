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
from dataclasses import dataclass
from typing import Any

from .errors import StandardErrorCode
from .search_health import SearchHealthManager
from .search_provider import (
    SearchProvider,
    SearchRequest,
    SearchResponse,
)


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
    ):
        """Initialize the SearchService.

        Args:
            providers: List of SearchProvider instances to use, in priority order.
            config: Optional configuration. Uses defaults if not provided.
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

        # Statistics
        self.total_requests = 0
        self.total_fallbacks = 0
        self.total_errors = 0
        self.last_used_provider: str | None = None

    def _is_provider_available(self, name: str) -> bool:
        """Check if a provider is available (circuit not open)."""
        backend = self.health_manager.get_backend(name)
        return backend is not None and backend.can_use()

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute a search with fallback and circuit breaking.

        Tries providers in order until one succeeds. Providers with open
        circuits are skipped. If all providers fail, returns a standardized
        error response.

        Args:
            request: The search request.

        Returns:
            SearchResponse with results or error information.
        """
        self.total_requests += 1
        errors: list[SearchResponse] = []

        for provider in self.providers:
            # Skip providers with open circuits
            if not self._is_provider_available(provider.name):
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
                    self.last_used_provider = provider.name
                    if len(errors) > 0:
                        self.total_fallbacks += 1
                    return response
                else:
                    # Provider returned an error response
                    self.health_manager.record_failure(
                        provider.name,
                        response.error_message or "Unknown error",
                    )
                    errors.append(response)

            except asyncio.TimeoutError:
                self.health_manager.record_failure(provider.name, "Timeout")
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

    if not providers:
        raise RuntimeError("No search providers could be initialized")

    service_config = SearchServiceConfig(
        circuit_failure_threshold=getattr(config, "circuit_failure_threshold", 5),
        circuit_recovery_time=getattr(config, "circuit_recovery_time", 60),
        request_timeout=getattr(config, "search_timeout", 30.0),
    )

    return SearchService(providers=providers, config=service_config)
