"""Web search backends.

Primary backend: Bing (direct HTML scraping, no API key required, works in
most network environments including China via cn.bing.com).

The interface is designed so additional backends (DuckDuckGo, Google Custom
Search, SerpAPI) can be plugged in later.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from .cache import Cache
from .config import Config


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    position: int


class SearchEngine:
    """Search engine wrapper with caching.

    Uses Bing search via direct HTTP requests (no API key).  Results are
    cached by query string to avoid hitting the search engine repeatedly.
    """

    BING_URL = "https://www.bing.com/search"

    def __init__(self, config: Config, cache: Optional[Cache] = None):
        self.config = config
        self.cache = cache
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.request_timeout),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        region: str = "wt-wt",
        safe_search: Optional[bool] = None,
    ) -> list[SearchResult]:
        """Perform a web search and return structured results.

        Args:
            query: The search query.
            max_results: Maximum number of results (default from config).
            region: Region code (kept for API compatibility; Bing uses
                ``setlang``/``cc`` params internally).
            safe_search: Whether to enable safe search (default from config).

        Returns:
            A list of ``SearchResult`` objects.
        """
        limit = max_results or self.config.search_max_results
        safe = safe_search if safe_search is not None else self.config.search_safe_search
        cache_key = f"search:bing:{query}:{limit}:{safe}"

        # Check cache
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                raw = json.loads(cached["value"])
                return [SearchResult(**item) for item in raw]

        # Perform search
        results = await self._bing_search(query, limit, safe)

        # Store in cache
        if self.cache and results and results[0].position > 0:
            self.cache.set(
                cache_key,
                json.dumps([r.__dict__ for r in results]),
                content_type="application/json",
            )

        return results

    async def _bing_search(
        self, query: str, max_results: int, safe_search: bool
    ) -> list[SearchResult]:
        """Search Bing by scraping the HTML results page."""
        client = await self._get_client()
        params = {
            "q": query,
            "count": min(max_results + 5, 50),  # request a few extra in case of ads
            "setlang": "en",
        }
        if safe_search:
            params["adlt"] = "moderate"
        else:
            params["adlt"] = "off"

        try:
            response = await client.get(self.BING_URL, params=params)
            response.raise_for_status()
        except Exception as exc:
            return [
                SearchResult(
                    title=f"[Search error: {type(exc).__name__}]",
                    url="",
                    snippet=str(exc)[:500],
                    position=0,
                )
            ]

        # Parse results in a thread to avoid blocking the event loop
        results = await asyncio.to_thread(
            self._parse_bing_results, response.text, max_results
        )
        return results

    @staticmethod
    def _parse_bing_results(html: str, max_results: int) -> list[SearchResult]:
        """Parse Bing search results from HTML.

        Bing results are in ``<li class="b_algo">`` elements.  Each contains
        an ``<h2><a>`` for the title/link and a ``<p>`` or ``.b_caption p``
        for the snippet.
        """
        results: list[SearchResult] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            algo_items = soup.select("li.b_algo")

            for i, item in enumerate(algo_items):
                if len(results) >= max_results:
                    break

                # Title and URL
                link = item.select_one("h2 a") or item.select_one("a")
                if not link:
                    continue
                title = link.get_text(strip=True)
                url = link.get("href", "")

                # Skip non-http links (Bing sometimes has internal links)
                if not url.startswith("http"):
                    continue

                # Snippet
                snippet = ""
                caption_p = item.select_one(".b_caption p") or item.select_one("p")
                if caption_p:
                    snippet = caption_p.get_text(strip=True)

                # Fallback: try .b_lineclamp classes
                if not snippet:
                    for cls in [".b_lineclamp1", ".b_lineclamp2", ".b_lineclamp3", ".b_lineclamp4"]:
                        el = item.select_one(cls)
                        if el:
                            snippet = el.get_text(strip=True)
                            break

                if title or url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            position=len(results) + 1,
                        )
                    )
        except Exception:
            pass

        return results
