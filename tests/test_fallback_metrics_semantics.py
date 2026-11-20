"""Pin the distinction the live test now relies on.

`total_fallbacks` means "a fallback rescued us"; `fallback_attempted()` means "a
provider was left for another". On a blocked egress the first stays 0 while the
second is True — conflating them is what made CI report "fallback never triggered"
when the fallback had run and failed.

Tested without a network: the flag is derived from `fallback_reasons`.
"""

from __future__ import annotations

from webscout_mcp.orchestration.search_service import SearchService, SearchServiceConfig


class _StubProvider:
    """Minimal provider: the service validates that one exists but the metrics
    under test are plain attributes, so nothing is ever called."""

    name = "stub"

    async def search(self, request):  # pragma: no cover - never invoked
        raise AssertionError("the stub provider must not be called")


def _service() -> SearchService:
    return SearchService(providers=[_StubProvider()], config=SearchServiceConfig())


def test_no_fallbacks_yet():
    svc = _service()
    assert svc.fallback_attempted() is False
    assert svc.total_fallbacks == 0


def test_a_recorded_reason_counts_as_an_attempt():
    svc = _service()
    svc.fallback_reasons["PROVIDER_ERROR"] = 1
    assert svc.fallback_attempted() is True
    # the rescue counter is untouched: nothing was rescued
    assert svc.total_fallbacks == 0, (
        'total_fallbacks must keep meaning "rescued", not "attempted"; fallback_rate is derived from it'
    )


def test_the_two_metrics_are_independent():
    """A rescue increments both; a failed attempt increments only one."""
    rescued = _service()
    rescued.fallback_reasons["PROVIDER_ERROR"] = 1
    rescued.total_fallbacks = 1

    failed = _service()
    failed.fallback_reasons["PROVIDER_ERROR"] = 1

    assert rescued.fallback_attempted() and rescued.total_fallbacks == 1
    assert failed.fallback_attempted() and failed.total_fallbacks == 0
