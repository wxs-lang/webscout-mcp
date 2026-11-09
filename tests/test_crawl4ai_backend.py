"""Tests for the Crawl4AI HTTP sidecar backend."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from webscout_mcp.crawl4ai_backend import Crawl4AIBrowserBackend
from webscout_mcp.fetch_provider import FetchRequest


@pytest.fixture(autouse=True)
def _bypass_ssrf_guard():
    # Unit tests focus on backend behavior, not SSRF. The SSRF guard is
    # covered in test_url_safety.py and tests/live/test_crawl4ai_e2e.py.
    with patch(
        "webscout_mcp.crawl4ai_backend.assert_redirect_chain_safe",
        new=AsyncMock(return_value=type("R", (), {"safe": True, "reason": ""})()),
    ):
        yield


@dataclass
class Cfg:
    crawl4ai_enabled: bool = True
    crawl4ai_base_url: str = "http://localhost:11235"
    crawl4ai_api_token: str = "secret"
    crawl4ai_timeout: float = 5.0


def _make(base_url: str = "http://localhost:11235", enabled: bool = True) -> Crawl4AIBrowserBackend:
    return Crawl4AIBrowserBackend(Cfg(crawl4ai_enabled=enabled, crawl4ai_base_url=base_url))


class _Resp:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._p = payload or {}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=MagicMock(), response=MagicMock())


@pytest.mark.asyncio
async def test_disabled_reports_config_error():
    p = _make(enabled=False)
    r = await p.fetch(FetchRequest(url="https://x"))
    assert r.error is not None
    assert "not configured" in r.error


@pytest.mark.asyncio
async def test_happy_path_parses_markdown():
    p = _make()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.post = AsyncMock(
        return_value=_Resp(
            200,
            {
                "results": [
                    {
                        "markdown": "# Hello\nbody",
                        "metadata": {"title": "Hi", "url": "https://x"},
                    }
                ]
            },
        )
    )
    r = await p.fetch(FetchRequest(url="https://x"))
    assert r.is_success
    assert "Hello" in r.content
    assert r.provider == "crawl4ai"
    assert r.metadata["browser"] == "crawl4ai"


@pytest.mark.asyncio
async def test_auth_error():
    p = _make()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.post = AsyncMock(return_value=_Resp(403))
    r = await p.fetch(FetchRequest(url="https://x"))
    assert r.is_error
    assert r.retryable is False


@pytest.mark.asyncio
async def test_timeout():
    p = _make()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.post = AsyncMock(side_effect=httpx.TimeoutException("slow"))
    r = await p.fetch(FetchRequest(url="https://x"))
    assert r.is_error
    assert r.retryable is True


@pytest.mark.asyncio
async def test_connect_error():
    p = _make()
    p._client = MagicMock(spec=httpx.AsyncClient)
    p._client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    r = await p.fetch(FetchRequest(url="https://x"))
    assert r.is_error
    assert r.retryable is True


@pytest.mark.asyncio
async def test_close():
    p = _make()
    await p._get_client()
    assert p._client is not None
    await p.close()
    assert p._client is None
