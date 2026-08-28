"""Tests for TLS fingerprint-aware fetcher (tls_fetcher module)."""

import pytest

from webscout_mcp.tls_fetcher import (
    TLSFetcher,
    TLSFetchResult,
    get_supported_browsers,
    is_tls_fetcher_available,
)


@pytest.mark.skipif(not is_tls_fetcher_available(), reason="curl_cffi not installed")
class TestTLSFetcherAvailability:
    """Test TLS fetcher availability and browser support."""

    def test_is_available(self):
        assert is_tls_fetcher_available() is True

    def test_get_supported_browsers(self):
        browsers = get_supported_browsers()
        assert len(browsers) > 0
        assert "chrome120" in browsers
        assert "firefox120" in browsers
        assert "safari17_0" in browsers

    def test_supported_browsers_list(self):
        assert "chrome99" in TLSFetcher.SUPPORTED_BROWSERS
        assert "chrome120" in TLSFetcher.SUPPORTED_BROWSERS
        assert "firefox120" in TLSFetcher.SUPPORTED_BROWSERS
        assert "safari17_0" in TLSFetcher.SUPPORTED_BROWSERS


@pytest.mark.skipif(not is_tls_fetcher_available(), reason="curl_cffi not installed")
class TestTLSFetcherInit:
    """Test TLS fetcher initialization."""

    def test_init_default(self):
        fetcher = TLSFetcher()
        assert fetcher.impersonate == "chrome120"
        assert fetcher.timeout == 30.0
        assert fetcher.max_redirects == 5
        assert fetcher.verify is True

    def test_init_custom(self):
        fetcher = TLSFetcher(
            impersonate="firefox120",
            timeout=60.0,
            max_redirects=10,
            verify=False,
        )
        assert fetcher.impersonate == "firefox120"
        assert fetcher.timeout == 60.0
        assert fetcher.max_redirects == 10
        assert fetcher.verify is False

    def test_init_invalid_browser(self):
        with pytest.raises(ValueError, match="Unsupported browser"):
            TLSFetcher(impersonate="invalid_browser")

    def test_context_manager(self):
        with TLSFetcher() as fetcher:
            assert fetcher.impersonate == "chrome120"
        # Session should be closed after context exit


@pytest.mark.skipif(not is_tls_fetcher_available(), reason="curl_cffi not installed")
class TestTLSFetchResult:
    """Test TLS fetch result."""

    def test_result_to_dict(self):
        result = TLSFetchResult(
            url="https://example.com",
            final_url="https://example.com/page",
            status_code=200,
            content="<html>test</html>",
            content_type="text/html",
            headers={"Content-Type": "text/html"},
            impersonated_browser="chrome120",
        )
        data = result.to_dict()
        assert data["url"] == "https://example.com"
        assert data["final_url"] == "https://example.com/page"
        assert data["status_code"] == 200
        assert data["content"] == "<html>test</html>"
        assert data["content_type"] == "text/html"
        assert data["impersonated_browser"] == "chrome120"
        assert data["error"] is None

    def test_result_with_error(self):
        result = TLSFetchResult(
            url="https://example.com",
            final_url="https://example.com",
            status_code=0,
            error="ConnectionError: timeout",
            impersonated_browser="chrome120",
        )
        data = result.to_dict()
        assert data["status_code"] == 0
        assert data["error"] == "ConnectionError: timeout"
        assert data["content"] == ""
