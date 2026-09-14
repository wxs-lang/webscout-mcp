"""Tests for the FetchProvider abstraction (v1.2.0).

Covers the FetchProvider interface, HTTPFetchProvider wrapping the smart
Fetcher, error mapping to standard codes, and the BrowserFetchProvider
abstraction placeholder.
"""

from __future__ import annotations

import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.fetch_provider import (
    BrowserFetchProvider,
    FetchProvider,
    FetchRequest,
    FetchResponse,
    FetchStatus,
    HTTPFetchProvider,
    _map_fetch_error,
)
from webscout_mcp.search_provider import ProviderHealth, ProviderHealthStatus


class FakeFetchResult:
    """Mimics webscout_mcp.fetcher.FetchResult."""

    def __init__(
        self,
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        title="Example",
        content="<html><body>Hello</body></html>",
        content_type="text/html",
        extracted=False,
        cached=False,
        error=None,
        metadata=None,
    ):
        self.url = url
        self.final_url = final_url
        self.status_code = status_code
        self.title = title
        self.content = content
        self.content_type = content_type
        self.extracted = extracted
        self.cached = cached
        self.error = error
        self.metadata = metadata or {}


class FakeFetcher:
    """Minimal fake for the smart Fetcher."""

    def __init__(self, result):
        self.result = result
        self.config = object()
        self.closed = False
        self.stats = {"total_requests": 1, "success_rate": 1.0, "average_response_time": 0.2}

    async def fetch(self, **kwargs):
        return self.result

    def get_stats(self):
        return self.stats

    async def close(self):
        self.closed = True


# ----------------------------------------------------------------------
# FetchRequest / FetchResponse
# ----------------------------------------------------------------------
def test_fetch_request_strips_url():
    req = FetchRequest(url="  https://example.com  ")
    assert req.url == "https://example.com"


def test_fetch_response_from_success_result():
    result = FakeFetchResult()
    response = FetchResponse.from_fetch_result(result, provider="http", latency_ms=123.4)
    assert response.is_success is True
    assert response.is_error is False
    assert response.provider == "http"
    assert response.latency_ms == 123.4
    assert response.error is None
    assert response.status_code == 200


def test_fetch_response_from_error_result():
    result = FakeFetchResult(status_code=0, error="Timeout while connecting")
    response = FetchResponse.from_fetch_result(result, provider="http", latency_ms=10.0)
    assert response.is_success is False
    assert response.is_error is True
    assert response.error_code == StandardErrorCode.FETCH_TIMEOUT
    assert response.retryable is True


def test_fetch_response_status_codes():
    ok = FetchResponse.from_fetch_result(FakeFetchResult(status_code=200), "http", 0)
    assert ok.is_success
    assert not ok.is_error

    forbidden = FetchResponse.from_fetch_result(FakeFetchResult(status_code=403), "http", 0)
    assert not forbidden.is_success
    assert forbidden.is_error
    assert forbidden.error_code == StandardErrorCode.FETCH_FORBIDDEN

    rate = FetchResponse.from_fetch_result(FakeFetchResult(status_code=429), "http", 0)
    assert rate.error_code == StandardErrorCode.FETCH_RATE_LIMITED
    assert rate.retryable is True

    server = FetchResponse.from_fetch_result(FakeFetchResult(status_code=503), "http", 0)
    assert server.error_code == StandardErrorCode.FETCH_SERVER_ERROR


def test_fetch_response_to_dict():
    response = FetchResponse.from_fetch_result(FakeFetchResult(), "http", 12.34)
    d = response.to_dict()
    assert d["url"] == "https://example.com"
    assert d["provider"] == "http"
    assert d["latency_ms"] == 12.34
    assert d["error_code"] is None


# ----------------------------------------------------------------------
# Error mapping
# ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "error", "expected_code", "expected_retryable"),
    [
        (403, None, StandardErrorCode.FETCH_FORBIDDEN, False),
        (429, None, StandardErrorCode.FETCH_RATE_LIMITED, True),
        (408, None, StandardErrorCode.FETCH_TIMEOUT, True),
        (504, None, StandardErrorCode.FETCH_TIMEOUT, True),
        (500, None, StandardErrorCode.FETCH_SERVER_ERROR, True),
        (404, None, StandardErrorCode.FETCH_FAILED, False),
        (0, "Connection refused", StandardErrorCode.FETCH_CONNECTION_ERROR, True),
        (0, "DNS resolution failed", StandardErrorCode.FETCH_DNS_ERROR, True),
        (0, "SSL certificate verify failed", StandardErrorCode.FETCH_SSL_ERROR, True),
        (0, "Robots.txt disallowed", StandardErrorCode.FETCH_ROBOTS_DENIED, False),
        (0, "Content too large: 999999", StandardErrorCode.FETCH_CONTENT_TOO_LARGE, False),
        (0, "Unexpected error", StandardErrorCode.FETCH_FAILED, True),
    ],
)
def test_map_fetch_error(status, error, expected_code, expected_retryable):
    code, retryable = _map_fetch_error(status, error)
    assert code == expected_code
    assert retryable == expected_retryable


# ----------------------------------------------------------------------
# HTTPFetchProvider
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_http_provider_fetch_success():
    fetcher = FakeFetcher(FakeFetchResult())
    provider = HTTPFetchProvider(fetcher)
    response = await provider.fetch(FetchRequest(url="https://example.com"))
    assert response.is_success
    assert response.provider == "http"
    assert provider.name == "http"


@pytest.mark.asyncio
async def test_http_provider_fetch_error_updates_health():
    fetcher = FakeFetcher(FakeFetchResult(status_code=0, error="timeout"))
    provider = HTTPFetchProvider(fetcher)
    response = await provider.fetch(FetchRequest(url="https://example.com"))
    assert response.is_error
    health = provider.get_health()
    assert health.error_count == 1
    assert health.last_error is not None


@pytest.mark.asyncio
async def test_http_provider_health_from_stats():
    fetcher = FakeFetcher(FakeFetchResult())
    provider = HTTPFetchProvider(fetcher)
    health = await provider.health()
    assert isinstance(health, ProviderHealth)
    assert health.success_rate == 1.0
    assert health.status == ProviderHealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_http_provider_close_closes_fetcher():
    fetcher = FakeFetcher(FakeFetchResult())
    provider = HTTPFetchProvider(fetcher)
    await provider.close()
    assert fetcher.closed is True


@pytest.mark.asyncio
async def test_http_provider_stats_exposed():
    fetcher = FakeFetcher(FakeFetchResult())
    provider = HTTPFetchProvider(fetcher)
    stats = provider.get_stats()
    assert stats["total_requests"] == 1


@pytest.mark.asyncio
async def test_http_provider_handles_exception():
    class ExplodingFetcher:
        config = object()

        async def fetch(self, **kwargs):
            raise RuntimeError("boom")

        def get_stats(self):
            return {}

        async def close(self):
            pass

    provider = HTTPFetchProvider(ExplodingFetcher())
    response = await provider.fetch(FetchRequest(url="https://example.com"))
    assert response.is_error
    assert "boom" in response.error
    assert response.error_code is not None


# ----------------------------------------------------------------------
# BrowserFetchProvider (abstraction placeholder)
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_browser_provider_not_implemented():
    provider = BrowserFetchProvider()
    assert provider.name == "browser"
    with pytest.raises(NotImplementedError):
        await provider.fetch(FetchRequest(url="https://example.com"))


@pytest.mark.asyncio
async def test_browser_provider_health_unknown():
    provider = BrowserFetchProvider()
    health = await provider.health()
    assert health.status == ProviderHealthStatus.UNKNOWN


# ----------------------------------------------------------------------
# Interface contract
# ----------------------------------------------------------------------
def test_fetch_provider_is_abstract():
    with pytest.raises(TypeError):
        FetchProvider(config=None)  # type: ignore[abstract]


def test_fetch_status_enum_values():
    assert FetchStatus.SUCCESS.value == "success"
    assert FetchStatus.ERROR.value == "error"
