"""Content-quality counters must record every fetch path, exactly once.

The counters were only written by FetchService. Any caller driving Fetcher
directly recorded nothing - and the live test suite does exactly that, so the
SLO report showed fetches=0 and the rolling baseline had nothing to average.

Adding the counter to Fetcher then counted one fetch twice, because
HTTPFetchProvider wraps Fetcher and FetchService records the final served
result. by_backend showed both 'fetcher' and 'fast-http' for a single fetch,
inflating the denominator and skewing the usable rate.

These tests pin both halves: every path records, and none records twice.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from webscout_mcp.config import Config
from webscout_mcp.fetcher import Fetcher, FetchResult
from webscout_mcp.observability import get_observability_summary, reset_for_tests


@pytest.fixture(autouse=True)
def _clean():
    reset_for_tests()
    yield
    reset_for_tests()


def _cq() -> dict:
    return get_observability_summary()["content_quality"]


def _result(content: str = "x" * 3000, status_code: int = 200, metadata: dict | None = None) -> FetchResult:
    return FetchResult(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=status_code,
        content=content,
        metadata=metadata or {},
    )


def _fetcher() -> Fetcher:
    cfg = Config()
    tmp = Path(tempfile.mkdtemp())
    return Fetcher(cfg, cache=None)


@pytest.mark.asyncio
async def test_direct_fetcher_fetch_records_quality():
    """The live-test path: Fetcher used directly, no FetchService."""
    f = _fetcher()
    f._fetch_inner = AsyncMock(return_value=_result())
    await f.fetch("https://example.com/a")
    cq = _cq()
    assert cq["fetches"] == 1
    assert cq["by_backend"] == {"fetcher": 1}


@pytest.mark.asyncio
async def test_fetcher_records_the_returned_content_length():
    f = _fetcher()
    f._fetch_inner = AsyncMock(return_value=_result(content="y" * 1234))
    await f.fetch("https://example.com/a")
    assert _cq()["chars_returned_total"] == 1234


@pytest.mark.asyncio
async def test_fetcher_records_truncation_from_metadata():
    f = _fetcher()
    f._fetch_inner = AsyncMock(
        return_value=_result(
            content="z" * 8000,
            metadata={"pre_limit_content_chars": 200000, "truncated_by_output_limit": True, "omitted_chars": 192000},
        )
    )
    await f.fetch("https://example.com/a", max_chars=8000)
    cq = _cq()
    assert cq["truncated_by_output_limit"] == 1
    assert cq["chars_omitted_total"] == 192000


@pytest.mark.asyncio
async def test_fetcher_marks_http_errors_as_failed():
    f = _fetcher()
    f._fetch_inner = AsyncMock(return_value=_result(content="", status_code=404))
    await f.fetch("https://example.com/a")
    assert _cq()["by_status"].get("failed") == 1


@pytest.mark.asyncio
async def test_record_quality_false_skips_recording():
    """The inner call from HTTPFetchProvider must not double-count."""
    f = _fetcher()
    f._fetch_inner = AsyncMock(return_value=_result())
    await f.fetch("https://example.com/a", record_quality=False)
    assert _cq()["fetches"] == 0


@pytest.mark.asyncio
async def test_one_fetchservice_fetch_records_exactly_one_data_point():
    """Regression: this used to record twice ('fetcher' and 'fast-http').

    A doubled denominator makes a usable rate that divides by the wrong number,
    which is worse than no metric at all - it looks precise and is wrong.
    """
    from webscout_mcp.eval_services import aclose_services, configure_eval_run
    from webscout_mcp.fetch_provider import FetchRequest

    services = configure_eval_run("double-count-test")
    try:
        services["fetch_service"]._fallback_http = None
        await services["fetch_service"].fetch(
            FetchRequest(
                url="https://example.com/",
                extract=True,
                output_format="markdown",
                max_chars=5000,
                bypass_cache=True,
            )
        )
        cq = _cq()
        assert cq["fetches"] == 1, f"expected exactly 1, got {cq['fetches']} via {cq['by_backend']}"
        assert cq["by_backend"] == {"fast-http": 1}, "the service layer owns the record, not the wrapped fetcher"
    finally:
        await aclose_services(services)


@pytest.mark.asyncio
async def test_repeated_fetches_accumulate():
    f = _fetcher()
    f._fetch_inner = AsyncMock(return_value=_result())
    for _ in range(3):
        await f.fetch("https://example.com/a")
    assert _cq()["fetches"] == 3
