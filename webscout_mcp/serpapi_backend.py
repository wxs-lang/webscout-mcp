"""SerpAPI search backend for webscout-mcp.

Provides a stable, API-based search backend as an alternative to HTML scraping.
SerpAPI supports Google, Bing, DuckDuckGo, and other search engines via a
unified JSON API. This backend is more stable than HTML scraping because it
doesn't depend on search engine DOM structure.

Usage:
    Set SERPAPI_API_KEY environment variable, then use "serpapi" as a backend.

Configuration:
    - SERPAPI_API_KEY: Your SerpAPI API key (required)
    - SERPAPI_ENGINE: Search engine to use (default: "google")
    - SERPAPI_TIMEOUT: Request timeout in seconds (default: 30)

Note:
    SerpAPI is a paid service with a free tier. See https://serpapi.com for details.
    This backend is optional - if no API key is configured, it will be skipped.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .exceptions import SearchError
from .logging_config import get_logger
from .search import SearchBackend, SearchResult

log = get_logger(__name__)


class SerpAPIBackend(SearchBackend):
    """SerpAPI search backend - stable JSON API alternative to HTML scraping.

    Supports Google, Bing, DuckDuckGo, and other engines via SerpAPI.
    More stable than HTML scraping because it doesn't depend on DOM structure.
    """

    name = "serpapi"
    SERPAPI_URL = "https://serpapi.com/search.json"

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.api_key = getattr(config, "serpapi_api_key", None) or os.getenv("SERPAPI_API_KEY")
        self.engine = getattr(config, "serpapi_engine", None) or os.getenv("SERPAPI_ENGINE", "google")
        self.timeout = getattr(config, "serpapi_timeout", None) or float(os.getenv("SERPAPI_TIMEOUT", "30"))

    @property
    def is_configured(self) -> bool:
        """Check if SerpAPI is configured with an API key."""
        return bool(self.api_key)

    async def search(
        self, query: str, max_results: int, safe_search: bool, region: str = "wt-wt"
    ) -> list[SearchResult]:
        """Perform a search via SerpAPI.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            safe_search: Whether to enable safe search.
            region: Region code (e.g., "wt-wt" for worldwide).

        Returns:
            List of SearchResult objects.

        Raises:
            SearchError: If the API request fails or returns invalid data.
        """
        if not self.is_configured:
            raise SearchError("SerpAPI API key not configured. Set SERPAPI_API_KEY environment variable.")

        client = await self._get_client()

        # Parse region for country/language
        country = "us"
        language = "en"
        if "-" in region:
            parts = region.split("-")
            if len(parts) == 2:
                language = parts[0].lower()
                country = parts[1].lower()

        params = {
            "q": query,
            "engine": self.engine,
            "api_key": self.api_key,
            "num": min(max_results + 5, 100),
            "hl": language,
            "gl": country,
        }

        if safe_search:
            params["safe"] = "active"

        try:
            log.info(
                "searching via SerpAPI",
                extra={"engine": self.engine, "query": query, "max_results": max_results},
            )

            response = await client.get(
                self.SERPAPI_URL,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()

            # Check for API errors
            if "error" in data:
                raise SearchError(f"SerpAPI error: {data['error']}")

            # Extract organic results
            organic_results = data.get("organic_results", [])
            if not organic_results:
                log.warning("SerpAPI returned no organic results", extra={"query": query})
                return []

            results = []
            for i, item in enumerate(organic_results[:max_results], start=1):
                title = item.get("title", "")
                url = item.get("link", "")
                snippet = item.get("snippet", "") or item.get("description", "")

                # Skip results without URL
                if not url:
                    continue

                result = SearchResult(
                    position=i,
                    title=self._clean_text(title),
                    url=url,
                    snippet=self._clean_text(snippet),
                    backend=self.name,
                )
                results.append(result)

            log.info(
                "SerpAPI search succeeded",
                extra={"query": query, "count": len(results), "engine": self.engine},
            )

            return results

        except httpx.HTTPStatusError as exc:
            error_msg = f"SerpAPI HTTP error: {exc.response.status_code}"
            if exc.response.status_code == 401:
                error_msg += " - Invalid API key"
            elif exc.response.status_code == 429:
                error_msg += " - Rate limit exceeded"
            log.error("SerpAPI request failed", extra={"query": query, "error": error_msg})
            raise SearchError(error_msg) from exc
        except httpx.RequestError as exc:
            error_msg = f"SerpAPI request failed: {exc}"
            log.error("SerpAPI request error", extra={"query": query, "error": error_msg})
            raise SearchError(error_msg) from exc
        except (KeyError, ValueError, TypeError) as exc:
            error_msg = f"SerpAPI response parsing error: {exc}"
            log.error("SerpAPI parsing error", extra={"query": query, "error": error_msg})
            raise SearchError(error_msg) from exc


def is_serpapi_available() -> bool:
    """Check if SerpAPI is available (API key configured)."""
    return bool(os.getenv("SERPAPI_API_KEY"))
