"""End-to-end wiring tests: FetchService.fetch() must feed content-quality metrics.

These exercise the real orchestration path with fake providers, so they prove
the instrumentation is connected rather than merely present. No network.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from webscout_mcp.fetch_provider import FetchRequest, FetchResponse
from webscout_mcp.fetch_service import FetchService
from webscout_mcp.observability import (
    THIN_CONTENT_CHARS,
    get_observability_summary,
    reset_for_tests,
)
from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter


class _FakeProvider:
    name: str = "fake"
    capabilities: set[ProviderCapability] = set()

    def __init__(self, name, capabilities, response=None, error=None):
        self.name = name
        self.capabilities = capabilities
        self.fetch = AsyncMock(return_value=response) if response is not None else AsyncMock(side_effect=error)
        self.close = AsyncMock()

    def get_health(self):
        return {"status": "ok"}


def _registry(providers):
    router = ProviderRouter(
        provider_names=[p.name for p in providers],
        cost_tiers={p.name: ProviderCostTier.FREE for p in providers},
        capabilities={p.name: set(p.capabilities) for p in providers},
    )
    reg = ProviderRegistry(router=router)
    for p in providers:
        reg.register(p, capabilities=p.capabilities)
    return reg


def _resp(content: str, *, metadata=None, status_code: int = 200) -> FetchResponse:
    return FetchResponse(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=status_code,
        provider="http",
        title="Example",
        content=content,
        content_type="text/html",
        extracted=True,
        metadata=metadata or {},
    )


@pytest.fixture(autouse=True)
def _clean():
    reset_for_tests()
    yield
    reset_for_tests()


def _cq() -> dict:
    return get_observability_summary()["content_quality"]


@pytest.mark.asyncio
async def test_successful_fetch_records_usable_content():
    body = "x" * 2000
    reg = _registry([_FakeProvider("http", {ProviderCapability.FETCH}, _resp(body))])
    await FetchService(registry=reg).fetch(FetchRequest(url="https://example.com/a"))

    cq = _cq()
    assert cq["fetches"] == 1
    assert cq["usable"] == 1
    assert cq["thin"] == 0
    assert cq["by_backend"].get("http", 0) + cq["by_backend"].get("fast-http", 0) >= 1


@pytest.mark.asyncio
async def test_captcha_shell_body_is_recorded_as_thin():
    """The exact regression class the v1.9.0 A/B run exposed: HTTP 200, no content."""
    reg = _registry([_FakeProvider("http", {ProviderCapability.FETCH}, _resp("Captcha required"))])
    await FetchService(registry=reg).fetch(FetchRequest(url="https://example.com/a"))

    cq = _cq()
    assert cq["fetches"] == 1
    assert cq["thin"] == 1
    assert cq["usable"] == 0
    assert cq["usable_rate"] == 0.0


@pytest.mark.asyncio
async def test_truncation_metadata_is_recorded():
    meta = {
        "pre_limit_content_chars": 200000,
        "truncated_by_output_limit": True,
        "omitted_chars": 192000,
        "content_total_chars": 200000,
    }
    reg = _registry([_FakeProvider("http", {ProviderCapability.FETCH}, _resp("x" * 8000, metadata=meta))])
    await FetchService(registry=reg).fetch(FetchRequest(url="https://example.com/a", max_chars=8000))

    cq = _cq()
    assert cq["truncated_by_output_limit"] == 1
    assert cq["chars_omitted_total"] == 192000
    assert cq["usable"] == 1, "a full window of a long page is usable"


@pytest.mark.asyncio
async def test_zero_length_body_is_recorded_as_empty():
    reg = _registry([_FakeProvider("http", {ProviderCapability.FETCH}, _resp(""))])
    await FetchService(registry=reg).fetch(FetchRequest(url="https://example.com/a"))

    cq = _cq()
    assert cq["empty"] == 1
    assert cq["chars_returned_total"] == 0


@pytest.mark.asyncio
async def test_threshold_boundary_through_service():
    reg = _registry([_FakeProvider("http", {ProviderCapability.FETCH}, _resp("x" * THIN_CONTENT_CHARS))])
    await FetchService(registry=reg).fetch(FetchRequest(url="https://example.com/a"))
    assert _cq()["usable"] == 1


@pytest.mark.asyncio
async def test_metrics_are_emitted_even_when_fetch_fails():
    """A failed fetch must still produce a data point, not silence."""
    reg = _registry(
        [
            _FakeProvider("http", {ProviderCapability.FETCH}, error=RuntimeError("boom")),
        ]
    )
    try:
        await FetchService(registry=reg).fetch(FetchRequest(url="https://example.com/a"))
    except Exception:  # noqa: BLE001 - failure mode is not what this test asserts
        pass

    cq = _cq()
    assert cq["fetches"] >= 1, "a failed fetch must still be counted"
