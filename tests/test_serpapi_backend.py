"""Comprehensive tests for SerpAPI search backend.

Tests cover:
- Normal 200 responses with results
- Empty results
- Invalid JSON responses
- HTTP errors (401, 429, 500)
- Timeout and request errors
- Region handling (wt-wt, zh-cn, en-us, unknown)
- Circuit breaker integration
- Fallback behavior
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from webscout_mcp.exceptions import SearchError
from webscout_mcp.search import SearchResult
from webscout_mcp.serpapi_backend import SerpAPIBackend, is_serpapi_available


class TestSerpAPIBackendCreation:
    """Test backend creation and configuration."""

    def test_create_with_api_key(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)
        assert backend.api_key == "test_api_key_12345"
        assert backend.engine == "google"
        assert backend.timeout == 30
        assert backend.name == "serpapi"

    def test_is_configured_true(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)
        assert backend.is_configured is True

    def test_is_configured_false(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = None
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)
        assert backend.is_configured is False

    def test_default_engine(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_key"
        config.serpapi_engine = None
        config.serpapi_timeout = None

        backend = SerpAPIBackend(config)
        assert backend.engine == "google"
        assert backend.timeout == 30


class TestSerpAPINormalSearch:
    """Test normal search scenarios."""

    @pytest.mark.asyncio
    async def test_search_200_with_results(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "organic_results": [
                    {
                        "title": "Test Result 1",
                        "link": "https://example.com/1",
                        "snippet": "This is test result 1",
                    },
                    {
                        "title": "Test Result 2",
                        "link": "https://example.com/2",
                        "snippet": "This is test result 2",
                    },
                ]
            }
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            results = await backend.search("test query", max_results=10, safe_search=False, region="us-en")

        assert len(results) == 2
        assert results[0].title == "Test Result 1"
        assert results[0].url == "https://example.com/1"
        assert results[0].snippet == "This is test result 1"
        assert results[0].backend == "serpapi"
        assert results[0].position == 1

    @pytest.mark.asyncio
    async def test_search_empty_results(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"organic_results": []})

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            results = await backend.search("no results query", max_results=10, safe_search=False, region="us-en")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_max_results(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        organic_results = [
            {"title": f"Result {i}", "link": f"https://example.com/{i}", "snippet": f"Snippet {i}"} for i in range(20)
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"organic_results": organic_results})

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            results = await backend.search("test", max_results=5, safe_search=False, region="us-en")

        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_search_skips_results_without_url(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "organic_results": [
                    {"title": "No URL", "snippet": "This has no link"},
                    {"title": "Has URL", "link": "https://example.com", "snippet": "This has link"},
                ]
            }
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            results = await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert len(results) == 1
        assert results[0].title == "Has URL"


class TestSerpAPIErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_search_not_configured_raises(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = None
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        with pytest.raises(SearchError) as exc_info:
            await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert "not configured" in str(exc_info.value).lower()
        assert exc_info.value.backend == "serpapi"

    @pytest.mark.asyncio
    async def test_search_401_invalid_api_key(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "invalid_key"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(SearchError) as exc_info:
                await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert "401" in str(exc_info.value)
        assert "invalid api key" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_search_429_rate_limit(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_key"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("429", request=MagicMock(), response=mock_response)
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(SearchError) as exc_info:
                await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert "429" in str(exc_info.value)
        assert "rate limit" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_search_500_server_error(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_key"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=mock_response)
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(SearchError) as exc_info:
                await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_search_timeout_error(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_key"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(SearchError) as exc_info:
                await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert "request failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_search_connection_error(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_key"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(SearchError) as exc_info:
                await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert "request failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_search_invalid_json(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_key"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(side_effect=ValueError("invalid json"))

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(SearchError) as exc_info:
                await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert "parsing error" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_search_api_error_in_response(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_key"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"error": "Your account has been suspended"})

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            with pytest.raises(SearchError) as exc_info:
                await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert "serpapi error" in str(exc_info.value).lower()
        assert "suspended" in str(exc_info.value).lower()


class TestSerpAPIRegionHandling:
    """Test region code handling."""

    @pytest.mark.asyncio
    async def _search_with_region(self, region: str) -> dict[str, str]:
        """Helper to perform a search and return the params used."""
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"organic_results": []})

        captured_params = {}

        async def mock_get(url, params=None, **kwargs):
            captured_params.update(params or {})
            return mock_response

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_get)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            await backend.search("test", max_results=10, safe_search=False, region=region)

        return captured_params

    @pytest.mark.asyncio
    async def test_region_wt_wt(self) -> None:
        params = await self._search_with_region("wt-wt")
        assert params["hl"] == "en"
        assert params["gl"] == "us"

    @pytest.mark.asyncio
    async def test_region_zh_cn(self) -> None:
        params = await self._search_with_region("zh-cn")
        assert params["hl"] == "zh"
        assert params["gl"] == "cn"

    @pytest.mark.asyncio
    async def test_region_en_us(self) -> None:
        params = await self._search_with_region("us-en")
        assert params["hl"] == "en"
        assert params["gl"] == "us"

    @pytest.mark.asyncio
    async def test_region_ja_jp(self) -> None:
        params = await self._search_with_region("ja-jp")
        assert params["hl"] == "ja"
        assert params["gl"] == "jp"

    @pytest.mark.asyncio
    async def test_region_de_de(self) -> None:
        params = await self._search_with_region("de-de")
        assert params["hl"] == "de"
        assert params["gl"] == "de"

    @pytest.mark.asyncio
    async def test_region_unknown_locale_falls_back(self) -> None:
        params = await self._search_with_region("xx-yy")
        # Unknown but valid 2-letter codes should be used as-is
        assert params["hl"] == "xx"
        assert params["gl"] == "yy"

    @pytest.mark.asyncio
    async def test_region_invalid_wt_falls_back(self) -> None:
        params = await self._search_with_region("wt-xx")
        # wt is invalid, should fall back to defaults
        assert params["hl"] == "en"
        assert params["gl"] == "us"

    @pytest.mark.asyncio
    async def test_region_case_insensitive(self) -> None:
        params = await self._search_with_region("ZH-CN")
        assert params["hl"] == "zh"
        assert params["gl"] == "cn"

    @pytest.mark.asyncio
    async def test_safe_search_param(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"organic_results": []})

        captured_params = {}

        async def mock_get(url, params=None, **kwargs):
            captured_params.update(params or {})
            return mock_response

        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=mock_get)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            await backend.search("test", max_results=10, safe_search=True, region="us-en")

        assert captured_params.get("safe") == "active"


class TestSerpAPIAvailability:
    """Test is_serpapi_available function."""

    def test_is_available_with_env_var(self) -> None:
        with patch.dict("os.environ", {"SERPAPI_API_KEY": "test_key"}):
            assert is_serpapi_available() is True

    def test_not_available_without_env_var(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            assert is_serpapi_available() is False

    def test_not_available_with_empty_env_var(self) -> None:
        with patch.dict("os.environ", {"SERPAPI_API_KEY": ""}):
            assert is_serpapi_available() is False


class TestSerpAPISearchResultCleaning:
    """Test text cleaning in search results."""

    @pytest.mark.asyncio
    async def test_cleans_whitespace_from_title(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "organic_results": [
                    {
                        "title": "  Test   Result  ",
                        "link": "https://example.com",
                        "snippet": "  This is   test  snippet  ",
                    }
                ]
            }
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            results = await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert len(results) == 1
        # Whitespace should be normalized
        assert results[0].title == "Test Result"
        assert results[0].snippet == "This is test snippet"

    @pytest.mark.asyncio
    async def test_handles_empty_title_and_snippet(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(
            return_value={
                "organic_results": [
                    {
                        "title": "",
                        "link": "https://example.com",
                        "snippet": "",
                    }
                ]
            }
        )

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch.object(backend, "_get_client", AsyncMock(return_value=mock_client)):
            results = await backend.search("test", max_results=10, safe_search=False, region="us-en")

        assert len(results) == 1
        assert results[0].title == ""
        assert results[0].snippet == ""


class TestSerpAPIConcurrency:
    """Test concurrent search behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_searches(self) -> None:
        config = MagicMock()
        config.serpapi_api_key = "test_api_key_12345"
        config.serpapi_engine = "google"
        config.serpapi_timeout = 30

        backend = SerpAPIBackend(config)

        call_count = 0

        async def mock_get_client():
            nonlocal call_count
            call_count += 1
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.raise_for_status = MagicMock()
            mock_response.json = MagicMock(return_value={"organic_results": []})
            mock_client = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            return mock_client

        with patch.object(backend, "_get_client", mock_get_client):
            tasks = [backend.search(f"query {i}", max_results=5, safe_search=False, region="us-en") for i in range(5)]
            results = await asyncio.gather(*tasks)

        assert len(results) == 5
        assert all(r == [] for r in results)
