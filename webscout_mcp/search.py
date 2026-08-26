"""Web search backends with automatic failover.

Supports multiple search engines (Bing, DuckDuckGo HTML) and tries them in
order until one returns results. Each backend is a self-contained HTML
scraper - no API keys required.

Backends are tried in the order configured by ``search_backends`` (env:
``WEBSCOUT_SEARCH_BACKENDS``, comma-separated). Default: ``bing,duckduckgo``.
"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

import httpx
from bs4 import BeautifulSoup

from .cache import Cache
from .config import Config
from .exceptions import AllBackendsFailedError, SearchError
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class SearchResult:
    """A single search result."""
    title: str
    url: str
    snippet: str
    position: int
    backend: str = ""


class SearchBackend(ABC):
    """Base class for search backends."""
    name: str = "base"

    def __init__(self, config: Config) -> None:
        self.config = config
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

    @abstractmethod
    async def search(
        self, query: str, max_results: int, safe_search: bool
    ) -> list[SearchResult]:
        ...


class BingBackend(SearchBackend):
    """Bing search via direct HTML scraping."""
    name = "bing"
    BING_URL = "https://www.bing.com/search"

    async def search(
        self, query: str, max_results: int, safe_search: bool
    ) -> list[SearchResult]:
        client = await self._get_client()
        params = {
            "q": query,
            "count": min(max_results + 5, 50),
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
            raise SearchError(query, self.name, f"{type(exc).__name__}: {exc}") from exc
        results = await asyncio.to_thread(self._parse_results, response.text, max_results)
        if not results:
            raise SearchError(query, self.name, "no results parsed from Bing HTML")
        return results

    @staticmethod
    def _parse_results(html: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            for item in soup.select("li.b_algo"):
                if len(results) >= max_results:
                    break
                link = item.select_one("h2 a") or item.select_one("a")
                if not link:
                    continue
                title = link.get_text(strip=True)
                url = link.get("href", "")
                if not url.startswith("http"):
                    continue
                snippet = ""
                caption_p = item.select_one(".b_caption p") or item.select_one("p")
                if caption_p:
                    snippet = caption_p.get_text(strip=True)
                if not snippet:
                    for cls in [".b_lineclamp1", ".b_lineclamp2", ".b_lineclamp3", ".b_lineclamp4"]:
                        el = item.select_one(cls)
                        if el:
                            snippet = el.get_text(strip=True)
                            break
                if title or url:
                    results.append(SearchResult(
                        title=title, url=url, snippet=snippet,
                        position=len(results) + 1, backend="bing",
                    ))
        except Exception:
            pass
        return results


class DuckDuckGoHTMLBackend(SearchBackend):
    """DuckDuckGo HTML version (https://html.duckduckgo.com/html/).

    No JavaScript, no API key. Works well as a fallback when Bing is
    blocked or changes its markup.
    """
    name = "duckduckgo"
    DDG_URL = "https://html.duckduckgo.com/html/"

    async def search(
        self, query: str, max_results: int, safe_search: bool
    ) -> list[SearchResult]:
        client = await self._get_client()
        data = {"q": query}
        if safe_search:
            data["kp"] = "1"
        else:
            data["kp"] = "-2"
        try:
            response = await client.post(self.DDG_URL, data=data)
            response.raise_for_status()
        except Exception as exc:
            raise SearchError(query, self.name, f"{type(exc).__name__}: {exc}") from exc
        results = await asyncio.to_thread(self._parse_results, response.text, max_results)
        if not results:
            raise SearchError(query, self.name, "no results parsed from DuckDuckGo HTML")
        return results

    @staticmethod
    def _extract_real_url(ddg_url: str) -> str:
        if ddg_url.startswith("http"):
            return ddg_url
        try:
            parsed = urlparse(ddg_url)
            if parsed.path == "/l/" and "uddg" in parse_qs(parsed.query):
                return unquote(parse_qs(parsed.query)["uddg"][0])
        except Exception:
            pass
        return ddg_url

    @classmethod
    def _parse_results(cls, html: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            for item in soup.select("div.result"):
                if len(results) >= max_results:
                    break
                link = item.select_one("a.result__a")
                if not link:
                    continue
                title = link.get_text(strip=True)
                url = cls._extract_real_url(link.get("href", ""))
                if not url.startswith("http"):
                    continue
                snippet = ""
                snippet_el = item.select_one("a.result__snippet") or item.select_one(".result__snippet")
                if snippet_el:
                    snippet = snippet_el.get_text(strip=True)
                if title or url:
                    results.append(SearchResult(
                        title=title, url=url, snippet=snippet,
                        position=len(results) + 1, backend="duckduckgo",
                    ))
        except Exception:
            pass
        return results


_BACKENDS: dict[str, type[SearchBackend]] = {
    "bing": BingBackend,
    "duckduckgo": DuckDuckGoHTMLBackend,
}


class SearchEngine:
    """Search engine wrapper with caching and automatic backend failover."""

    def __init__(
        self,
        config: Config,
        cache: Optional[Cache] = None,
        backends: Optional[list[str]] = None,
    ) -> None:
        self.config = config
        self.cache = cache
        backend_names = backends or self._parse_backend_list(config)
        self._backends: list[SearchBackend] = []
        for name in backend_names:
            cls = _BACKENDS.get(name.lower())
            if cls:
                self._backends.append(cls(config))
            else:
                log.warning("unknown search backend, skipping", backend=name)
        if not self._backends:
            log.warning("no valid backends configured, falling back to bing")
            self._backends.append(BingBackend(config))

    @staticmethod
    def _parse_backend_list(config: Config) -> list[str]:
        import os
        raw = os.environ.get("WEBSCOUT_SEARCH_BACKENDS", "bing,duckduckgo")
        return [b.strip() for b in raw.split(",") if b.strip()]

    async def close(self) -> None:
        for backend in self._backends:
            await backend.close()

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        region: str = "wt-wt",
        safe_search: Optional[bool] = None,
    ) -> list[SearchResult]:
        """Perform a web search with automatic backend failover."""
        limit = max_results or self.config.search_max_results
        safe = safe_search if safe_search is not None else self.config.search_safe_search
        backend_names = ",".join(b.name for b in self._backends)
        cache_key = f"search:{backend_names}:{query}:{limit}:{safe}"
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                raw = json.loads(cached["value"])
                return [SearchResult(**item) for item in raw]
        failures: dict[str, str] = {}
        for backend in self._backends:
            try:
                log.info("searching", backend=backend.name, query=query, max_results=limit)
                results = await backend.search(query, limit, safe)
                if results:
                    if self.cache:
                        self.cache.set(
                            cache_key,
                            json.dumps([r.__dict__ for r in results]),
                            content_type="application/json",
                        )
                    log.info("search succeeded", backend=backend.name, query=query, count=len(results))
                    return results
                failures[backend.name] = "returned empty results"
            except SearchError as exc:
                failures[backend.name] = str(exc)
                log.warning("search backend failed", backend=backend.name, query=query, error=str(exc))
            except Exception as exc:
                failures[backend.name] = f"{type(exc).__name__}: {exc}"
                log.warning("search backend unexpected error", backend=backend.name, query=query, error=type(exc).__name__)
        raise AllBackendsFailedError(query, failures)
