"""Tests for the ProviderRouter capability-aware routing (v1.2.0).

Covers the extended router: dynamic registration, capability filtering,
health-based ranking and circuit-aware selection.
"""

from __future__ import annotations

import pytest

from webscout_mcp.provider_router import (
    ProviderCapability,
    ProviderCostTier,
    ProviderHealthScorer,
    ProviderMetrics,
    ProviderRouter,
    ProviderScore,
)


@pytest.fixture
def router():
    return ProviderRouter(
        provider_names=["bing", "duckduckgo", "tavily"],
        cost_tiers={
            "bing": ProviderCostTier.FREE,
            "duckduckgo": ProviderCostTier.FREE,
            "tavily": ProviderCostTier.PAID,
        },
        prefer_free=True,
        min_score_threshold=30.0,
        capabilities={
            "bing": {ProviderCapability.SEARCH},
            "duckduckgo": {ProviderCapability.SEARCH},
            "tavily": {ProviderCapability.SEARCH},
        },
    )


def test_initial_ranking_all_healthy(router):
    ranked = router.get_ranked_providers()
    assert [s.name for s in ranked] == ["bing", "duckduckgo", "tavily"]


def test_capability_filter(router):
    router.set_capabilities(
        {
            "bing": {ProviderCapability.SEARCH},
            "duckduckgo": {ProviderCapability.FETCH},
            "tavily": {ProviderCapability.SEARCH, ProviderCapability.FETCH},
        }
    )
    search_ranked = router.get_ranked_providers(capability=ProviderCapability.SEARCH)
    assert {s.name for s in search_ranked} == {"bing", "tavily"}

    fetch_ranked = router.get_ranked_providers(capability=ProviderCapability.FETCH)
    assert {s.name for s in fetch_ranked} == {"duckduckgo", "tavily"}

    # Capability that nobody provides -> empty
    assert router.get_ranked_providers(capability=ProviderCapability.BROWSER) == []


def test_get_next_provider_with_capability(router):
    router.set_capabilities(
        {
            "bing": {ProviderCapability.SEARCH},
            "duckduckgo": {ProviderCapability.FETCH},
            "tavily": {ProviderCapability.SEARCH},
        }
    )
    assert router.get_next_provider(capability=ProviderCapability.SEARCH) == "bing"
    assert router.get_next_provider(capability=ProviderCapability.FETCH) == "duckduckgo"
    # Exclude the top pick
    assert router.get_next_provider(capability=ProviderCapability.SEARCH, exclude=["bing"]) == "tavily"


def test_no_capability_returns_all(router):
    # Backward compatible: capability=None means no filtering
    assert router.get_next_provider() == "bing"
    assert len(router.get_ranked_providers()) == 3


def test_provider_without_capability_map_supports_all():
    # Providers absent from the capability map support everything (backward compat)
    r = ProviderRouter(provider_names=["legacy"])
    assert r.get_ranked_providers(capability=ProviderCapability.SEARCH) != []
    assert r.get_next_provider(capability=ProviderCapability.FETCH) == "legacy"


def test_router_ranks_healthy_over_slow(router):
    router.record_result("bing", True, 3000.0)
    router.record_result("duckduckgo", True, 180.0)
    router.record_result("tavily", True, 300.0)
    ranked = router.get_ranked_providers()
    assert ranked[0].name == "duckduckgo"


def test_circuit_open_moves_provider_to_end(router):
    router.set_circuit_open("bing")
    ranked = router.get_ranked_providers()
    assert ranked[-1].name == "bing"
    # get_next_provider skips it
    assert router.get_next_provider() != "bing"


def test_circuit_open_excludes_provider(router):
    router.set_circuit_open("bing")
    assert router.get_next_provider() == "duckduckgo"


def test_all_circuits_open_returns_none(router):
    for name in ["bing", "duckduckgo", "tavily"]:
        router.set_circuit_open(name)
    assert router.get_next_provider() is None


def test_low_score_provider_skipped_but_half_open_allowed():
    r = ProviderRouter(provider_names=["good", "bad"], min_score_threshold=50.0)
    r.record_result("bad", False, 100.0, "timeout")
    r.record_result("bad", False, 100.0, "timeout")
    r.record_result("bad", False, 100.0, "timeout")
    # bad has very low success rate -> skipped
    assert r.get_next_provider() == "good"

    # Half-open providers are allowed for recovery
    r.set_circuit_open("bad")
    r.set_circuit_half_open("bad")
    next_name = r.get_next_provider(exclude=["good"])
    assert next_name == "bad"


def test_health_scorer_reasons(router):
    router.record_result("bing", True, 120.0)
    score = router.get_ranked_providers()[0]
    assert score.score > 0
    assert any("latency" in r.lower() for r in score.reasons)


def test_health_report_shape(router):
    report = router.get_health_report()
    assert report["routing_mode"] == "dynamic_health_based"
    assert len(report["providers"]) == 3
    first = report["providers"][0]
    for key in ["name", "score", "success_rate", "p95_latency_ms", "error_rate", "circuit_open", "cost_tier"]:
        assert key in first


def test_prefer_free_boost():
    r = ProviderRouter(
        provider_names=["free1", "paid1"],
        cost_tiers={"free1": ProviderCostTier.FREE, "paid1": ProviderCostTier.PAID},
        prefer_free=True,
    )
    # Same metrics for both; free wins on the boost
    r.record_result("free1", True, 500.0)
    r.record_result("paid1", True, 500.0)
    assert r.get_next_provider() == "free1"


def test_add_provider_after_init():
    r = ProviderRouter(provider_names=["existing"])
    r.add_provider("new", ProviderCostTier.LOW_COST)
    assert "new" in r.metrics
    assert r.cost_tiers["new"] == ProviderCostTier.LOW_COST
    assert r.get_next_provider() in ("existing", "new")


def test_scorer_calculates_score():
    metrics = ProviderMetrics(name="x")
    metrics.record_request(True, 100.0)
    metrics.record_request(True, 150.0)
    metrics.record_request(False, 2000.0, "timeout")
    scorer = ProviderHealthScorer(cost_tiers={"x": ProviderCostTier.FREE})
    score = scorer.calculate_score(metrics)
    assert isinstance(score, ProviderScore)
    assert 0.0 <= score.score <= 100.0
    assert score.name == "x"
    assert score.cost_tier == ProviderCostTier.FREE
