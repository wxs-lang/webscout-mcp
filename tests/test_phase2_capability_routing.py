"""Tests for Phase 2 capability-aware routing guarantees."""

from __future__ import annotations

import pytest

from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter


def test_registry_select_filters_by_capability():
    """Registry.select(FETCH) must never return a SEARCH or BROWSER provider."""
    router = ProviderRouter(
        provider_names=["bing", "duckduckgo", "http", "crawl4ai"],
        cost_tiers={n: ProviderCostTier.FREE for n in ["bing", "duckduckgo", "http", "crawl4ai"]},
        capabilities={
            "bing": {ProviderCapability.SEARCH},
            "duckduckgo": {ProviderCapability.SEARCH},
            "http": {ProviderCapability.FETCH},
            "crawl4ai": {ProviderCapability.BROWSER},
        },
    )
    reg = ProviderRegistry(router=router)
    # Register lightweight stand-ins (only name matters for select()).
    for name, caps in [
        ("bing", {ProviderCapability.SEARCH}),
        ("duckduckgo", {ProviderCapability.SEARCH}),
        ("http", {ProviderCapability.FETCH}),
        ("crawl4ai", {ProviderCapability.BROWSER}),
    ]:
        reg.register(type("P", (), {"name": name, "close": None, "get_health": dict}), capabilities=caps)

    assert reg.select(ProviderCapability.SEARCH) in ("bing", "duckduckgo")
    assert reg.select(ProviderCapability.FETCH) == "http"
    assert reg.select(ProviderCapability.BROWSER) == "crawl4ai"


def test_search_never_picks_fetch_or_browser():
    """When all four are registered, SEARCH selection never returns http/crawl4ai."""
    router = ProviderRouter(
        provider_names=["bing", "http", "crawl4ai"],
        cost_tiers={n: ProviderCostTier.FREE for n in ["bing", "http", "crawl4ai"]},
        capabilities={
            "bing": {ProviderCapability.SEARCH},
            "http": {ProviderCapability.FETCH},
            "crawl4ai": {ProviderCapability.BROWSER},
        },
    )
    # Even if we call get_next_provider with capability=SEARCH, only bing qualifies.
    assert router.get_next_provider(capability=ProviderCapability.SEARCH) == "bing"
    # FETCH picks http, not crawl4ai (BROWSER only).
    assert router.get_next_provider(capability=ProviderCapability.FETCH) == "http"
    # BROWSER picks crawl4ai, not http.
    assert router.get_next_provider(capability=ProviderCapability.BROWSER) == "crawl4ai"


def test_no_capability_filter_is_dangerous():
    """Sanity: without capability filter, the router would consider everyone.
    This pins the reason we must pass capability explicitly in SearchService."""
    router = ProviderRouter(
        provider_names=["bing", "http"],
        capabilities={
            "bing": {ProviderCapability.SEARCH},
            "http": {ProviderCapability.FETCH},
        },
    )
    # No filter -> http may be returned (which is the bug Phase 2 fixes).
    # With capability=SEARCH -> only bing.
    assert router.get_next_provider(capability=ProviderCapability.SEARCH) == "bing"
