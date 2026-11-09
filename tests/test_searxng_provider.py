"""Tests for the SearXNG SearchProvider (v1.2.1)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.search_provider import SearchRequest, SearchStatus
from webscout_mcp.searxng_provider import SearXNGSearchProvider


@dataclass
class FakeConfig:
    searxng_base_url: str = "https://searx.example.org"
    searxng_timeout: float = 5.0


def _make_provider(base_url: str = "https://searx.example.org") -> SearXNGSearchProvider:
    cfg = FakeConfig(searxng_base_url=base_url)
    return SearXNGSearchProvider(cfg)


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=MagicMock(), response=MagicMock())


@pytest.mark.asyncio
async def test_not_configured_returns_error():
    p = SearXNGSearchProvider(FakeConfig(searxng_base_url=""))
    resp = await p.search(SearchRequest(query="hello"))
    assert resp.status == SearchStatus.ERROR
    assert "not set" in resp.error_message
    assert resp.retryable is False


@pytest.mark.asyncio
async def test_success_parses_results():
    p = _make_provider()
    fake_resp = _FakeResponse(
        200,
        {
            "results": [
                {"title": "A", "url": "https://a.example", "content": "snippet a"},
                {"title": "B", "url": "https://b.example", "content": "snippet b"},
            ]
        },
    )
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.get = AsyncMock(return_value=fake_resp)

    resp = await p.search(SearchRequest(query="python", max_results=10))
    assert resp.status == SearchStatus.SUCCESS
    assert len(resp.results) == 2
    assert resp.results[0].title == "A"
    assert resp.results[0].backend == "searxng"
    # verify request params
    call_kwargs = p._client.get.call_args.kwargs
    assert call_kwargs["params"]["format"] == "json"
    assert call_kwargs["params"]["q"] == "python"


@pytest.mark.asyncio
async def test_empty_results_maps_to_empty():
    p = _make_provider()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.get = AsyncMock(return_value=_FakeResponse(200, {"results": []}))
    resp = await p.search(SearchRequest(query="nothing"))
    assert resp.status == SearchStatus.EMPTY


@pytest.mark.asyncio
async def test_rate_limited():
    p = _make_provider()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.get = AsyncMock(return_value=_FakeResponse(429))
    resp = await p.search(SearchRequest(query="x"))
    assert resp.status == SearchStatus.ERROR
    assert resp.error_type == StandardErrorCode.SEARCH_RATE_LIMITED
    assert resp.retryable is True


@pytest.mark.asyncio
async def test_forbidden_json_api():
    p = _make_provider()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.get = AsyncMock(return_value=_FakeResponse(403))
    resp = await p.search(SearchRequest(query="x"))
    assert resp.status == SearchStatus.ERROR
    assert resp.error_type == StandardErrorCode.SEARCH_BACKEND_FAILED
    # SEARCH_BACKEND_FAILED is auto-marked retryable; the router circuit-breaker
    # will stop trying after repeated 403s.
    assert resp.status == SearchStatus.ERROR


@pytest.mark.asyncio
async def test_server_error():
    p = _make_provider()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.get = AsyncMock(return_value=_FakeResponse(502))
    resp = await p.search(SearchRequest(query="x"))
    assert resp.status == SearchStatus.ERROR
    assert resp.error_type == StandardErrorCode.SEARCH_BACKEND_FAILED
    assert resp.retryable is True


@pytest.mark.asyncio
async def test_timeout():
    p = _make_provider()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    resp = await p.search(SearchRequest(query="x"))
    assert resp.status == SearchStatus.ERROR
    assert resp.error_type == StandardErrorCode.SEARCH_TIMEOUT
    assert resp.retryable is True


@pytest.mark.asyncio
async def test_connection_error():
    p = _make_provider()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    resp = await p.search(SearchRequest(query="x"))
    assert resp.status == SearchStatus.ERROR
    assert resp.error_type == StandardErrorCode.SEARCH_BACKEND_FAILED
    assert resp.retryable is True


@pytest.mark.asyncio
async def test_close_clients():
    p = _make_provider()
    await p._get_client()
    assert p._client is not None
    await p.close()
    assert p._client is None


def test_is_configured_flag():
    assert SearXNGSearchProvider(FakeConfig(searxng_base_url="x")).is_configured
    assert not SearXNGSearchProvider(FakeConfig(searxng_base_url="")).is_configured
