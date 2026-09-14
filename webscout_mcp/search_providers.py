"""Standard named SearchProvider implementations for webscout-mcp.

Provides the three concrete providers used by the default configuration:

- BingProvider: Bing HTML backend (free).
- DuckDuckGoProvider: DuckDuckGo HTML backend (free).
- TavilyProvider: Tavily Search API (paid, stable fallback).

All three implement the standardized ``SearchProvider`` interface so they can
be registered with the ProviderRegistry and routed by the dynamic router.
Bing/DDG wrap the existing backends via SearchBackendAdapter; Tavily wraps
the existing TavilySearchProvider (itself a SearchProvider).
"""

from __future__ import annotations

from typing import Any

from .logging_config import get_logger
from .search import BingBackend, DuckDuckGoHTMLBackend
from .search_provider import SearchProvider
from .search_provider_adapter import SearchBackendAdapter
from .tavily_provider import TavilySearchProvider

log = get_logger(__name__)


class BingProvider(SearchBackendAdapter):
    """Standard Bing search provider (free, HTML backend).

    Wraps the existing BingBackend so all routing/health logic speaks the
    standardized SearchProvider interface.
    """

    def __init__(self, config: Any) -> None:
        super().__init__(BingBackend(config), name="bing")


class DuckDuckGoProvider(SearchBackendAdapter):
    """Standard DuckDuckGo search provider (free, HTML backend).

    Wraps the existing DuckDuckGoHTMLBackend.
    """

    def __init__(self, config: Any) -> None:
        super().__init__(DuckDuckGoHTMLBackend(config), name="duckduckgo")


class TavilyProvider(TavilySearchProvider):
    """Standard Tavily search provider (paid, stable API).

    Inherits the existing TavilySearchProvider (a full SearchProvider),
    providing the canonical ``TavilyProvider`` name for registry use.
    """


def build_default_search_providers(config: Any) -> list[SearchProvider]:
    """Build the default search provider list in priority order.

    Attempts to initialize Bing, DuckDuckGo and Tavily (if configured).
    Providers that fail to initialize are skipped with a warning so the
    service can still start with whatever is available.

    Args:
        config: Application Config instance.

    Returns:
        List of initialized SearchProvider instances (never empty).
    """
    providers: list[SearchProvider] = []

    try:
        providers.append(BingProvider(config))
    except Exception as e:  # pragma: no cover - defensive
        log.warning("Could not initialize Bing provider: %s", e)

    try:
        providers.append(DuckDuckGoProvider(config))
    except Exception as e:  # pragma: no cover - defensive
        log.warning("Could not initialize DuckDuckGo provider: %s", e)

    try:
        tavily = TavilyProvider(config)
        if tavily.is_configured:
            providers.append(tavily)
            log.info("Tavily API provider initialized (stable fallback)")
        else:
            log.info("Tavily API key not configured, skipping Tavily provider")
    except Exception as e:  # pragma: no cover - defensive
        log.warning("Could not initialize Tavily provider: %s", e)

    if not providers:
        raise RuntimeError("No search providers could be initialized")

    return providers
