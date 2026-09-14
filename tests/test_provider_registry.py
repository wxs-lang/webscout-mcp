"""Tests for the ProviderRegistry (v1.2.0 Provider architecture).

Covers register / unregister / enable / disable / lookup / capability
filtering / health reporting, and integration with the dynamic router.
"""

from __future__ import annotations

import pytest

from webscout_mcp.provider_registry import ProviderRegistry, RegisteredProvider
from webscout_mcp.provider_router import (
    ProviderCapability,
    ProviderCostTier,
    ProviderMetrics,
    ProviderRouter,
)


class DummyProvider:
    """Minimal provider for registry tests."""

    def __init__(self, name: str):
        self.name = name
        self.closed = False
        self._health = {"status": "healthy", "provider": name}

    def get_health(self):
        return self._health

    async def close(self):
        self.closed = True


@pytest.fixture
def registry():
    return ProviderRegistry()


@pytest.fixture
def router():
    return ProviderRouter(provider_names=[])


def test_register_and_get(registry):
    p = DummyProvider("dummy")
    name = registry.register(p, {ProviderCapability.SEARCH}, ProviderCostTier.FREE)
    assert name == "dummy"
    assert registry.get("dummy") is p
    assert registry.names() == ["dummy"]
    assert registry.is_enabled("dummy")


def test_register_requires_name(registry):
    class NoName:
        pass

    with pytest.raises(ValueError):
        registry.register(NoName())


def test_register_idempotent_overwrite(registry):
    p1 = DummyProvider("a")
    p2 = DummyProvider("a")
    registry.register(p1, {ProviderCapability.SEARCH})
    registry.register(p2, {ProviderCapability.SEARCH})
    assert registry.get("a") is p2  # overwritten
    assert len(registry.names()) == 1


def test_unregister(registry):
    registry.register(DummyProvider("a"), {ProviderCapability.SEARCH})
    assert registry.unregister("a") is True
    assert registry.get("a") is None
    assert registry.unregister("a") is False  # already gone


def test_enable_disable(registry):
    registry.register(DummyProvider("a"), {ProviderCapability.SEARCH})
    assert registry.is_enabled("a")
    assert registry.disable("a") is True
    assert not registry.is_enabled("a")
    assert registry.enable("a") is True
    assert registry.is_enabled("a")
    # Unknown names return False
    assert registry.disable("nope") is False
    assert registry.enable("nope") is False


def test_capabilities(registry):
    registry.register(DummyProvider("search1"), {ProviderCapability.SEARCH})
    registry.register(DummyProvider("fetch1"), {ProviderCapability.FETCH, ProviderCapability.EXTRACT})
    assert registry.get_capabilities("search1") == {ProviderCapability.SEARCH}
    assert registry.get_capabilities("fetch1") == {ProviderCapability.FETCH, ProviderCapability.EXTRACT}
    by_cap = registry.get_providers_by_capability(ProviderCapability.FETCH)
    assert [p.name for p in by_cap] == ["fetch1"]
    assert registry.get_providers_by_capability(ProviderCapability.BROWSER) == []


def test_disabled_providers_excluded_from_capability_lookup(registry):
    registry.register(DummyProvider("search1"), {ProviderCapability.SEARCH})
    registry.register(DummyProvider("search2"), {ProviderCapability.SEARCH})
    registry.disable("search2")
    by_cap = registry.get_providers_by_capability(ProviderCapability.SEARCH)
    assert [p.name for p in by_cap] == ["search1"]


def test_health_report_structure(registry):
    registry.register(DummyProvider("a"), {ProviderCapability.SEARCH}, ProviderCostTier.FREE, "provider a")
    report = registry.health_report()
    assert report["total_providers"] == 1
    assert report["enabled_providers"] == 1
    assert report["providers"][0]["name"] == "a"
    assert report["providers"][0]["health"]["status"] == "healthy"
    assert report["providers"][0]["cost_tier"] == "free"
    assert "capabilities" in report["providers"][0]


def test_provider_health_single(registry):
    registry.register(DummyProvider("a"), {ProviderCapability.SEARCH})
    health = registry.provider_health("a")
    assert health is not None
    assert health["name"] == "a"
    assert registry.provider_health("missing") is None


def test_register_with_router_syncs_capabilities(router):
    reg = ProviderRegistry(router=router)
    reg.register(DummyProvider("bing"), {ProviderCapability.SEARCH}, ProviderCostTier.FREE)
    reg.register(DummyProvider("http"), {ProviderCapability.FETCH}, ProviderCostTier.FREE)
    # Router knows about both providers and their capabilities
    assert "bing" in router.metrics
    assert "http" in router.metrics
    assert router.capabilities["bing"] == {ProviderCapability.SEARCH}
    assert router.capabilities["http"] == {ProviderCapability.FETCH}


def test_disable_syncs_router_capabilities(router):
    reg = ProviderRegistry(router=router)
    reg.register(DummyProvider("a"), {ProviderCapability.SEARCH})
    reg.register(DummyProvider("b"), {ProviderCapability.SEARCH})
    reg.disable("b")
    # Disabled provider is removed from the router's capability map
    assert "b" not in router.capabilities


def test_select_without_router_falls_back_to_registration_order():
    reg = ProviderRegistry()  # no router
    reg.register(DummyProvider("first"), {ProviderCapability.SEARCH})
    reg.register(DummyProvider("second"), {ProviderCapability.SEARCH})
    assert reg.select(ProviderCapability.SEARCH) == "first"
    assert reg.select(ProviderCapability.SEARCH, exclude=["first"]) == "second"
    assert reg.select(ProviderCapability.FETCH) is None


def test_select_with_router_uses_health_scoring():
    router = ProviderRouter(provider_names=[], prefer_free=True)
    reg = ProviderRegistry(router=router)
    reg.register(DummyProvider("slow"), {ProviderCapability.SEARCH}, ProviderCostTier.FREE)
    reg.register(DummyProvider("fast"), {ProviderCapability.SEARCH}, ProviderCostTier.FREE)

    # Record results so the router has real metrics to score on
    router.record_result("slow", True, 2500.0)  # slow p95
    router.record_result("fast", True, 150.0)  # fast p95

    selected = reg.select(ProviderCapability.SEARCH)
    assert selected == "fast"


def test_select_respects_capability(router):
    reg = ProviderRegistry(router=router)
    reg.register(DummyProvider("search"), {ProviderCapability.SEARCH})
    reg.register(DummyProvider("fetch"), {ProviderCapability.FETCH})
    assert reg.select(ProviderCapability.SEARCH) == "search"
    assert reg.select(ProviderCapability.FETCH) == "fetch"
    assert reg.select(ProviderCapability.BROWSER) is None


@pytest.mark.asyncio
async def test_close_all(registry):
    p = DummyProvider("a")
    registry.register(p, {ProviderCapability.SEARCH})
    await registry.close_all()
    assert p.closed is True


def test_registered_provider_to_dict():
    rp = RegisteredProvider(
        name="x",
        provider=DummyProvider("x"),
        capabilities={ProviderCapability.SEARCH, ProviderCapability.FETCH},
        cost_tier=ProviderCostTier.PAID,
        description="test",
    )
    d = rp.to_dict()
    assert d["name"] == "x"
    assert d["capabilities"] == ["fetch", "search"]
    assert d["cost_tier"] == "paid"
    assert d["enabled"] is True


def test_router_add_provider_idempotent(router):
    router.add_provider("a", ProviderCostTier.PAID)
    router.add_provider("a", ProviderCostTier.PAID)
    assert len(router.metrics) == 1
    assert router.cost_tiers["a"] == ProviderCostTier.PAID


def test_registry_health_reports_disabled_and_open():
    router = ProviderRouter(provider_names=[])
    reg = ProviderRegistry(router=router)
    reg.register(DummyProvider("ok"), {ProviderCapability.SEARCH})
    reg.register(DummyProvider("off"), {ProviderCapability.SEARCH})
    reg.disable("off")
    router.set_circuit_open("ok")
    report = reg.health_report()
    assert report["enabled_providers"] == 1
    assert report["unavailable_providers"] == 2  # one disabled + one circuit open


def test_metrics_rolling_window():
    """ProviderMetrics window pruning behaves correctly."""
    metrics = ProviderMetrics(name="a", window_seconds=60)
    metrics.record_request(True, 100.0)
    metrics.record_request(False, 200.0, "timeout")
    assert metrics.success_rate == 0.5
    assert metrics.error_rate == 0.5
    assert metrics.total_requests == 2
    assert metrics.total_errors == 1
    assert metrics.error_timeout == 1
    # No requests -> assume healthy
    empty = ProviderMetrics(name="b")
    assert empty.success_rate == 1.0
    assert empty.p95_latency == 0.0
