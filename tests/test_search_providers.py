"""Tests for the standard named SearchProvider implementations (v1.2.0).

Covers BingProvider / DuckDuckGoProvider / TavilyProvider behavior through
the standardized SearchProvider interface, and the default provider factory.
"""

from __future__ import annotations

import pytest

from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier
from webscout_mcp.search import SearchResult
from webscout_mcp.search_provider import (
    ProviderHealth,
    SearchProvider,
    SearchRequest,
    SearchResponse,
)
from webscout_mcp.search_providers import (
    BingProvider,
    DuckDuckGoProvider,
    TavilyProvider,
    build_default_search_providers,
)


class FakeConfig:
    """Minimal config object for provider construction."""

    def __init__(self, **kwargs):
        self.request_timeout = 10.0
        self.proxy_http = ""
        self.proxy_https = ""
        self.tavily_api_key = ""
        self.tavily_timeout = 5.0
        for k, v in kwargs.items():
            setattr(self, k, v)


class FakeBackend:
    """Mimics a SearchBackend for adapter-based providers."""

    def __init__(self, config, results=None):
        self.config = config
        self.name = "fake"
        self.results = results or []
        self.closed = False

    async def search(self, query, max_results, safe_search, region="wt-wt"):
        if query == "boom":
            raise RuntimeError("backend exploded")
        return self.results

    async def close(self):
        self.closed = True


def _sample_results(n=3):
    return [
        SearchResult(
            title=f"Result {i}",
            url=f"https://example.com/{i}",
            snippet=f"Snippet {i}",
            position=i,
        )
        for i in range(1, n + 1)
    ]


# ----------------------------------------------------------------------
# Provider interface contract
# ----------------------------------------------------------------------
def test_search_provider_is_abstract():
    with pytest.raises(TypeError):
        SearchProvider(config=None)  # type: ignore[abstract]


def test_bing_provider_is_search_provider():
    assert issubclass(BingProvider, SearchProvider)


def test_duckduckgo_provider_is_search_provider():
    assert issubclass(DuckDuckGoProvider, SearchProvider)


def test_tavily_provider_is_search_provider():
    assert issubclass(TavilyProvider, SearchProvider)


def test_bing_provider_name():
    config = FakeConfig()
    p = BingProvider(config)
    assert p.name == "bing"


def test_duckduckgo_provider_name():
    config = FakeConfig()
    p = DuckDuckGoProvider(config)
    assert p.name == "duckduckgo"


def test_tavily_provider_name():
    config = FakeConfig(tavily_api_key="test-key")
    p = TavilyProvider(config)
    assert p.name == "tavily"


def test_tavily_not_configured():
    config = FakeConfig()  # no key
    p = TavilyProvider(config)
    assert p.is_configured is False


# ----------------------------------------------------------------------
# Adapter-based provider search behavior
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bing_provider_search_success(monkeypatch):
    config = FakeConfig()
    provider = BingProvider(config)
    # Replace the internal backend with a fake
    provider.backend = FakeBackend(config, results=_sample_results())
    response = await provider.search(SearchRequest(query="python"))
    assert response.is_success
    assert response.provider == "bing"
    assert len(response.results) == 3
    # Result backend attribution set to provider name
    assert all(r.backend == "bing" for r in response.results)


@pytest.mark.asyncio
async def test_bing_provider_search_empty(monkeypatch):
    config = FakeConfig()
    provider = BingProvider(config)
    provider.backend = FakeBackend(config, results=[])
    response = await provider.search(SearchRequest(query="nothing"))
    assert response.is_empty
    assert response.status.value == "empty"


@pytest.mark.asyncio
async def test_provider_search_error_maps_to_standard_code(monkeypatch):
    config = FakeConfig()
    provider = BingProvider(config)
    provider.backend = FakeBackend(config)
    response = await provider.search(SearchRequest(query="boom"))
    assert response.is_error
    assert response.error_type is not None
    assert response.provider == "bing"


@pytest.mark.asyncio
async def test_provider_health_updates_after_success():
    config = FakeConfig()
    provider = BingProvider(config)
    provider.backend = FakeBackend(config, results=_sample_results())
    await provider.search(SearchRequest(query="python"))
    health = provider.get_health()
    assert health.error_count == 0
    assert health.latency_ms >= 0


@pytest.mark.asyncio
async def test_provider_close_closes_backend():
    config = FakeConfig()
    provider = BingProvider(config)
    backend = FakeBackend(config)
    provider.backend = backend
    await provider.close()
    assert backend.closed is True


# ----------------------------------------------------------------------
# Tavily provider behavior
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tavily_unconfigured_returns_error():
    config = FakeConfig()  # no key
    provider = TavilyProvider(config)
    response = await provider.search(SearchRequest(query="python"))
    assert response.is_error
    assert response.retryable is False
    assert "key" in (response.error_message or "").lower()


@pytest.mark.asyncio
async def test_tavily_health():
    config = FakeConfig(tavily_api_key="test-key")
    provider = TavilyProvider(config)
    health = await provider.health()
    assert isinstance(health, ProviderHealth)
    assert health.provider == "tavily"


@pytest.mark.asyncio
async def test_tavily_close():
    config = FakeConfig(tavily_api_key="test-key")
    provider = TavilyProvider(config)
    await provider.close()  # should not raise


# ----------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------
def test_build_default_providers_without_tavily(monkeypatch):
    config = FakeConfig()  # no tavily key
    providers = build_default_search_providers(config)
    names = [p.name for p in providers]
    assert "bing" in names
    assert "duckduckgo" in names
    assert "tavily" not in names
    assert all(isinstance(p, SearchProvider) for p in providers)


def test_build_default_providers_with_tavily():
    config = FakeConfig(tavily_api_key="test-key")
    providers = build_default_search_providers(config)
    names = [p.name for p in providers]
    assert "tavily" in names


# ----------------------------------------------------------------------
# Registry integration
# ----------------------------------------------------------------------
def test_providers_register_with_capability():
    config = FakeConfig()
    registry = ProviderRegistry()
    bing = BingProvider(config)
    registry.register(
        bing,
        capabilities={ProviderCapability.SEARCH},
        cost_tier=ProviderCostTier.FREE,
    )
    assert registry.select(ProviderCapability.SEARCH) == "bing"
    report = registry.health_report()
    assert report["total_providers"] == 1
    assert report["providers"][0]["health"]["status"] is not None


@pytest.mark.asyncio
async def test_full_service_factory_integration():
    """create_search_service_from_config builds a working service + registry."""
    from webscout_mcp.provider_registry import ProviderRegistry
    from webscout_mcp.search_service import create_search_service_from_config

    config = FakeConfig()
    registry = ProviderRegistry()
    service = create_search_service_from_config(config, registry=registry)
    assert service is not None
    assert len(service.providers) >= 2
    # Search providers registered with SEARCH capability
    report = registry.health_report()
    assert report["total_providers"] >= 2
    assert all(
        ProviderCapability.SEARCH in {ProviderCapability(c) for c in p["capabilities"]} for p in report["providers"]
    )
    # Router wired
    assert service.router is not None
    await service.close()
