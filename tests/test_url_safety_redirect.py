"""Redirect-chain SSRF tests using mocked httpx."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webscout_mcp.url_safety import assert_redirect_chain_safe


def _make_stream_response(url: str, history_urls: list[str]):
    """Build a fake httpx response whose request.url and history look real."""
    req = MagicMock()
    req.url = url
    hist = []
    for h in history_urls:
        hr = MagicMock()
        hr.request.url = h
        hist.append(hr)
    resp = MagicMock()
    resp.request.url = url
    resp.history = hist
    return resp


@pytest.mark.asyncio
async def test_redirect_to_internal_is_blocked():
    fake = _make_stream_response("http://127.0.0.1/admin", ["http://public.example.com/"])

    @asynccontextmanager
    async def _stream(*a, **kw):
        yield fake

    mock_client = MagicMock()
    mock_client.stream = MagicMock(side_effect=_stream)

    with (
        patch(
            "webscout_mcp.url_safety.httpx.AsyncClient",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_client), __aexit__=AsyncMock(return_value=False)
            ),
        ),
        patch(
            "webscout_mcp.url_safety._resolve_host",
            return_value=["93.184.216.34"],
        ),
    ):
        result = await assert_redirect_chain_safe("http://public.example.com/")
    assert not result.safe
    assert "127.0.0.1" in result.reason


@pytest.mark.asyncio
async def test_redirect_to_public_allowed():
    fake = _make_stream_response("http://93.184.216.34/", ["http://public.example.com/"])

    @asynccontextmanager
    async def _stream(*a, **kw):
        yield fake

    mock_client = MagicMock()
    mock_client.stream = MagicMock(side_effect=_stream)

    with (
        patch(
            "webscout_mcp.url_safety.httpx.AsyncClient",
            return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_client), __aexit__=AsyncMock(return_value=False)
            ),
        ),
        patch(
            "webscout_mcp.url_safety._resolve_host",
            return_value=["93.184.216.34"],
        ),
    ):
        result = await assert_redirect_chain_safe("http://public.example.com/")
    assert result.safe
