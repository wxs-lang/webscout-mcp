"""Real SearXNG end-to-end smoke tests.

These tests run ONLY in the dedicated searxng-e2e workflow, which starts a
real SearXNG container via docker service. They validate:

  1. WebScout -> SearXNG real HTTP path returns parseable results.
  2. When SEARXNG_BASE_URL points to a dead port, the provider returns a
     retryable connection error (so the dynamic router can fall through).

No mocks. No recorded fixtures. Requires SEARXNG_BASE_URL to be set.
"""

from __future__ import annotations

import os

import pytest

from webscout_mcp.config import Config
from webscout_mcp.search_provider import SearchRequest, SearchStatus
from webscout_mcp.searxng_provider import SearXNGSearchProvider

pytestmark = pytest.mark.skipif(
    not os.environ.get("SEARXNG_BASE_URL"),
    reason="SEARXNG_BASE_URL not set (only runs in searxng-e2e workflow)",
)


def _config(base_url: str | None = None) -> Config:
    cfg = Config()
    cfg.searxng_base_url = base_url or os.environ.get("SEARXNG_BASE_URL", "")
    cfg.searxng_timeout = 10.0
    return cfg


@pytest.mark.asyncio
async def test_real_searxng_returns_results():
    provider = SearXNGSearchProvider(_config())
    try:
        resp = await provider.search(SearchRequest(query="python", max_results=5))
        assert resp.status in (SearchStatus.SUCCESS, SearchStatus.EMPTY), (
            f"expected success/empty, got {resp.status}: {resp.error_message}"
        )
        if resp.status == SearchStatus.SUCCESS:
            assert len(resp.results) >= 1
            assert resp.results[0].url.startswith("http")
        # Even EMPTY is acceptable (engine upstream may be cold); the point is
        # the JSON contract parsed without exception.
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_dead_instance_returns_retryable_error():
    # Point at a dead port so we exercise the real connect-error path.
    provider = SearXNGSearchProvider(_config(base_url="http://127.0.0.1:1"))
    try:
        resp = await provider.search(SearchRequest(query="anything", max_results=3))
        assert resp.status == SearchStatus.ERROR
        assert resp.retryable is True
        assert resp.error_type is not None
    finally:
        await provider.close()
