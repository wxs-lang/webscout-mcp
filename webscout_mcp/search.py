"""Web search backends with automatic failover.
Supports multiple search engines (Bing, DuckDuckGo HTML) and tries them in
order until one returns results.  Each backend is a self-contained HTML
scraper — no API keys required.
Backends are tried in the order configured by ``search_backends`` (env:
``WEBSCOUT_SEARCH_BACKENDS``, comma-separated).  Default: ``bing,duckduckgo``.
Enhanced features:
- Multi-backend result merging with deduplication
- Relevance-based result ranking
- Robust HTML parsing with multiple selector fallbacks
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup

from .cache import Cache
from .config import Config
from .exceptions import AllBackendsFailedError, SearchError
from .logging_config import get_logger
from .search_health import SearchHealthManager

log = get_logger(__name__)


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    snippet: str
    position: int
    backend: str = ""
    relevance_score: float = 0.0


class SearchBackend(ABC):
    """Base class for search backends."""

    name: str = "base"

    def __init__(self, config: Config) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            client_kwargs: dict = {
                "timeout": httpx.Timeout(self.config.request_timeout),
                "follow_redirects": True,
                "headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            }
            proxies: dict[str, str] = {}
            if self.config.proxy_http:
                proxies["http://"] = self.config.proxy_http
            if self.config.proxy_https:
                proxies["https://"] = self.config.proxy_https
            if proxies:
                client_kwargs["proxies"] = proxies
            self._client = httpx.AsyncClient(**client_kwargs)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @abstractmethod
    async def search(
        self, query: str, max_results: int, safe_search: bool, region: str = "wt-wt"
    ) -> list[SearchResult]:
        """Perform a search and return results."""
        ...

    @staticmethod
    def _clean_text(text: str) -> str:
        """Clean up text: normalize whitespace, remove extra spaces."""
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for comparison."""
        try:
            parsed = urlparse(url)
            host = parsed.hostname.lower() if parsed.hostname else ""
            path = parsed.path.rstrip("/") if parsed.path != "/" else ""
            query_params = parse_qs(parsed.query)
            tracking_params = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}
            clean_params = {k: v for k, v in query_params.items() if k.lower() not in tracking_params}
            clean_query = "&".join(f"{k}={v[0]}" for k, v in sorted(clean_params.items()))
            return f"{parsed.scheme}://{host}{path}" + (f"?{clean_query}" if clean_query else "")
        except Exception:
            return url.rstrip("/").lower()


class BingBackend(SearchBackend):
    """Bing search via direct HTML scraping with robust parsing."""

    name = "bing"
    BING_URL = "https://www.bing.com/search"

    async def search(
        self, query: str, max_results: int, safe_search: bool, region: str = "wt-wt"
    ) -> list[SearchResult]:
        client = await self._get_client()
        lang, cc = self._parse_region(region)
        params = {
            "q": query,
            "count": min(max_results + 10, 50),
            "setlang": lang,
        }
        if cc and cc != "wt":
            params["cc"] = cc
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
    def _parse_region(region: str) -> tuple[str, str]:
        """Parse region code like 'en-us' into (lang, country_code)."""
        parts = region.lower().replace("_", "-").split("-")
        lang = parts[0] if parts else "en"
        cc = parts[1].upper() if len(parts) > 1 else ""
        return lang, cc

    @classmethod
    def _parse_results(cls, html: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            selectors = [
                "li.b_algo",
                "li.b_algo h2",
                ".b_results > li",
                "div.b_algo",
                "li[data-bm]",
            ]
            items = []
            for selector in selectors:
                items = soup.select(selector)
                if items:
                    break
            for item in items:
                if len(results) >= max_results:
                    break
                link = None
                for link_sel in ["h2 a", "a", "h2 > a", ".b_title a"]:
                    link = item.select_one(link_sel)
                    if link:
                        break
                if not link:
                    continue
                title = cls._clean_text(link.get_text(strip=True))
                url = link.get("href", "")
                if not url.startswith("http"):
                    continue
                snippet = ""
                for snippet_sel in [
                    ".b_caption p",
                    "p",
                    ".b_lineclamp1",
                    ".b_lineclamp2",
                    ".b_lineclamp3",
                    ".b_lineclamp4",
                    ".b_snippet",
                    ".b_caption .b_lineclamp2",
                    "div.b_caption > p",
                ]:
                    snippet_el = item.select_one(snippet_sel)
                    if snippet_el:
                        snippet = cls._clean_text(snippet_el.get_text(strip=True))
                        if snippet:
                            break
                if title or url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            position=len(results) + 1,
                            backend="bing",
                        )
                    )
        except Exception as exc:
            log.warning("Bing parsing error", extra={"error": str(exc)})
        return results


class DuckDuckGoHTMLBackend(SearchBackend):
    """DuckDuckGo HTML version with robust parsing."""

    name = "duckduckgo"
    DDG_URL = "https://html.duckduckgo.com/html/"

    async def search(
        self, query: str, max_results: int, safe_search: bool, region: str = "wt-wt"
    ) -> list[SearchResult]:
        client = await self._get_client()
        data = {"q": query}
        if region and region.lower() != "wt-wt":
            parts = region.lower().replace("_", "-").split("-")
            if len(parts) >= 2:
                data["kl"] = f"{parts[1]}-{parts[0]}"
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
        """Extract the real URL from DuckDuckGo redirect links."""
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
            selectors = [
                "div.result",
                "div.results_links",
                "div.web-result",
                "div.result__body",
            ]
            items = []
            for selector in selectors:
                items = soup.select(selector)
                if items:
                    break
            for item in items:
                if len(results) >= max_results:
                    break
                link = None
                for link_sel in ["a.result__a", "a.result__url", "a", "h2 a"]:
                    link = item.select_one(link_sel)
                    if link:
                        break
                if not link:
                    continue
                title = cls._clean_text(link.get_text(strip=True))
                url = cls._extract_real_url(link.get("href", ""))
                if not url.startswith("http"):
                    continue
                snippet = ""
                for snippet_sel in [
                    "a.result__snippet",
                    ".result__snippet",
                    ".result__snippet b",
                    "div.result__snippet",
                    "span.result__snippet",
                ]:
                    snippet_el = item.select_one(snippet_sel)
                    if snippet_el:
                        snippet = cls._clean_text(snippet_el.get_text(strip=True))
                        if snippet:
                            break
                if title or url:
                    results.append(
                        SearchResult(
                            title=title,
                            url=url,
                            snippet=snippet,
                            position=len(results) + 1,
                            backend="duckduckgo",
                        )
                    )
        except Exception as exc:
            log.warning("DuckDuckGo parsing error", extra={"error": str(exc)})
        return results


class GoogleHTMLBackend(SearchBackend):
    """Google HTML search backend with robust parsing.

    Note: Google may block automated requests. Use with appropriate rate limiting
    and consider using other backends as fallback.
    """

    name = "google"
    GOOGLE_URL = "https://www.google.com/search"

    async def search(
        self, query: str, max_results: int, safe_search: bool, region: str = "wt-wt"
    ) -> list[SearchResult]:
        client = await self._get_client()
        params = {
            "q": query,
            "num": min(max_results + 5, 20),  # Request extra to account for ads
            "hl": "en",
        }
        if region and region.lower() != "wt-wt":
            parts = region.lower().replace("_", "-").split("-")
            if len(parts) >= 2:
                params["gl"] = parts[1]
                params["hl"] = parts[0]
        if safe_search:
            params["safe"] = "active"
        try:
            response = await client.get(self.GOOGLE_URL, params=params)
            response.raise_for_status()
        except Exception as exc:
            raise SearchError(query, self.name, f"{type(exc).__name__}: {exc}") from exc
        results = await asyncio.to_thread(self._parse_results, response.text, max_results)
        if not results:
            raise SearchError(query, self.name, "no results parsed from Google HTML")
        return results

    @classmethod
    def _parse_results(cls, html: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            # Multiple selectors for Google result containers
            selectors = [
                "div.g",
                "div.tF2Cxc",
                "div.MjjYud",
                "div.yuRUbf",
                "div[data-hveid]",
            ]
            items = []
            for selector in selectors:
                items = soup.select(selector)
                if items:
                    break
            for item in items:
                if len(results) >= max_results:
                    break
                # Find the link
                link = None
                for link_sel in ["a", "h3 a", "div.yuRUbf a"]:
                    link = item.select_one(link_sel)
                    if link and link.get("href", "").startswith("http"):
                        break
                if not link:
                    continue
                href = link.get("href", "")
                # Skip Google internal links
                if not href.startswith("http") or "google.com" in href:
                    continue
                # Find title
                title = ""
                title_el = item.select_one("h3")
                if title_el:
                    title = cls._clean_text(title_el.get_text(strip=True))
                if not title:
                    title = cls._clean_text(link.get_text(strip=True))
                # Find snippet
                snippet = ""
                for snippet_sel in [
                    "div.VwiC3b",
                    "span.aCOpRe",
                    "div.IsZvec",
                    "div[data-sncf]",
                    "span.st",
                ]:
                    snippet_el = item.select_one(snippet_sel)
                    if snippet_el:
                        snippet = cls._clean_text(snippet_el.get_text(strip=True))
                        if snippet:
                            break
                if title or href:
                    results.append(
                        SearchResult(
                            title=title,
                            url=href,
                            snippet=snippet,
                            position=len(results) + 1,
                            backend="google",
                        )
                    )
        except Exception as exc:
            log.warning("Google parsing error", extra={"error": str(exc)})
        return results


class BraveHTMLBackend(SearchBackend):
    """Brave Search HTML backend with robust parsing.

    Note: Brave may block automated requests. Use with appropriate rate limiting
    and consider using other backends as fallback.
    """

    name = "brave"
    BRAVE_URL = "https://search.brave.com/search"

    async def search(
        self, query: str, max_results: int, safe_search: bool, region: str = "wt-wt"
    ) -> list[SearchResult]:
        client = await self._get_client()
        params = {
            "q": query,
            "count": min(max_results + 5, 20),
        }
        if region and region.lower() != "wt-wt":
            parts = region.lower().replace("_", "-").split("-")
            if len(parts) >= 2:
                params["country"] = parts[1]
                params["lang"] = parts[0]
        if safe_search:
            params["safesearch"] = "moderate"
        try:
            response = await client.get(self.BRAVE_URL, params=params)
            response.raise_for_status()
        except Exception as exc:
            raise SearchError(query, self.name, f"{type(exc).__name__}: {exc}") from exc
        results = await asyncio.to_thread(self._parse_results, response.text, max_results)
        if not results:
            raise SearchError(query, self.name, "no results parsed from Brave HTML")
        return results

    @classmethod
    def _parse_results(cls, html: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            # Multiple selectors for Brave result containers
            selectors = [
                "div.snippet",
                "div.result",
                "div[data-loc]",
                "div.card",
                "article",
            ]
            items = []
            for selector in selectors:
                items = soup.select(selector)
                if items:
                    break
            for item in items:
                if len(results) >= max_results:
                    break
                # Find the link
                link = None
                for link_sel in ["a.result-header", "a.title", "a", "h2 a", "h3 a"]:
                    link = item.select_one(link_sel)
                    if link and link.get("href", "").startswith("http"):
                        break
                if not link:
                    continue
                href = link.get("href", "")
                # Skip Brave internal links
                if not href.startswith("http") or "brave.com" in href:
                    continue
                # Find title
                title = ""
                title_el = item.select_one("h2, h3, .title, .result-header")
                if title_el:
                    title = cls._clean_text(title_el.get_text(strip=True))
                if not title:
                    title = cls._clean_text(link.get_text(strip=True))
                # Find snippet
                snippet = ""
                for snippet_sel in [
                    "div.snippet-content",
                    "p.snippet",
                    "div.description",
                    "span.snippet",
                    "div.text",
                ]:
                    snippet_el = item.select_one(snippet_sel)
                    if snippet_el:
                        snippet = cls._clean_text(snippet_el.get_text(strip=True))
                        if snippet:
                            break
                if title or href:
                    results.append(
                        SearchResult(
                            title=title,
                            url=href,
                            snippet=snippet,
                            position=len(results) + 1,
                            backend="brave",
                        )
                    )
        except Exception as exc:
            log.warning("Brave parsing error", extra={"error": str(exc)})
        return results


# Registry of available backends
_BACKENDS: dict[str, type[SearchBackend]] = {
    "bing": BingBackend,
    "duckduckgo": DuckDuckGoHTMLBackend,
    "google": GoogleHTMLBackend,
    "brave": BraveHTMLBackend,
}


class SearchEngine:
    """Search engine wrapper with caching, automatic backend failover, and result merging."""

    def __init__(
        self,
        config: Config,
        cache: Cache | None = None,
        backends: list[str] | None = None,
        merge_backends: bool = False,
    ) -> None:
        self.config = config
        self.cache = cache
        self.merge_backends = merge_backends or getattr(config, "search_merge_backends", False)
        backend_names = backends or config.search_backends
        self._backends: list[SearchBackend] = []
        for name in backend_names:
            cls = _BACKENDS.get(name.lower())
            if cls:
                self._backends.append(cls(config))
            else:
                log.warning("unknown search backend, skipping", extra={"backend": name})
        if not self._backends:
            log.warning("no valid backends configured, falling back to bing")
            self._backends.append(BingBackend(config))

        # Initialize health manager for circuit breaking
        backend_names = [b.name for b in self._backends]
        self._health_manager = SearchHealthManager(
            backend_names=backend_names,
            failure_threshold=getattr(config, "search_circuit_failure_threshold", 5),
            recovery_time=getattr(config, "search_circuit_recovery_time", 60),
        )

    async def close(self) -> None:
        for backend in self._backends:
            await backend.close()

    def get_health_report(self) -> dict:
        """Get health report for all search backends.

        Returns:
            Dictionary with overall health score, per-backend status,
            and statistics. Includes circuit breaker status.
        """
        return self._health_manager.get_health_report()

    def reset_health(self) -> None:
        """Reset all backend health statistics and close all circuits."""
        self._health_manager.reset_all()

    @staticmethod
    def _deduplicate_results(results: list[SearchResult]) -> list[SearchResult]:
        """Remove duplicate URLs, preserving order and renumbering positions."""
        seen_urls: set[str] = set()
        unique: list[SearchResult] = []
        for r in results:
            normalized = SearchBackend._normalize_url(r.url)
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                unique.append(r)
        for i, r in enumerate(unique, start=1):
            r.position = i
        return unique

    @staticmethod
    def _calculate_relevance(result: SearchResult, query: str) -> float:
        """Calculate relevance score based on query term matches."""
        score = 0.0
        query_terms = set(re.findall(r"\w+", query.lower()))
        if not query_terms:
            return score
        title_terms = set(re.findall(r"\w+", result.title.lower()))
        title_matches = len(query_terms & title_terms)
        score += title_matches * 3.0
        snippet_terms = set(re.findall(r"\w+", result.snippet.lower()))
        snippet_matches = len(query_terms & snippet_terms)
        score += snippet_matches * 1.5
        url_terms = set(re.findall(r"\w+", result.url.lower()))
        url_matches = len(query_terms & url_terms)
        score += url_matches * 1.0
        if query_terms.issubset(title_terms | snippet_terms):
            score += 5.0
        if len(result.snippet) < 20:
            score -= 2.0
        return score

    def _rank_results(self, results: list[SearchResult], query: str) -> list[SearchResult]:
        """Rank results by relevance score, then by original position."""
        for r in results:
            r.relevance_score = self._calculate_relevance(r, query)
        results.sort(key=lambda r: (-r.relevance_score, r.position))
        for i, r in enumerate(results, start=1):
            r.position = i
        return results

    async def _search_single_backend(
        self, query: str, limit: int, safe: bool, region: str
    ) -> tuple[list[SearchResult], dict[str, str]]:
        """Try backends in order until one succeeds, with circuit breaker support."""
        failures: dict[str, str] = {}

        # Filter backends by health status (skip open circuits)
        available_names = self._health_manager.get_available_backends(
            [b.name for b in self._backends]
        )
        available_backends = [b for b in self._backends if b.name in available_names]

        if not available_backends:
            log.warning("all backends are circuit-broken, trying all anyway")
            available_backends = self._backends

        for backend in available_backends:
            try:
                log.info("searching", extra={"backend": backend.name, "query": query, "max_results": limit})
                results = await backend.search(query, limit, safe, region)
                if results:
                    log.info("search succeeded", extra={"backend": backend.name, "query": query, "count": len(results)})
                    self._health_manager.record_success(backend.name)
                    return results, failures
                failures[backend.name] = "returned empty results"
                self._health_manager.record_failure(backend.name, "empty results")
            except SearchError as exc:
                failures[backend.name] = str(exc)
                self._health_manager.record_failure(backend.name, str(exc))
                log.warning("search backend failed", extra={"backend": backend.name, "query": query, "error": str(exc)})
            except Exception as exc:
                failures[backend.name] = f"{type(exc).__name__}: {exc}"
                self._health_manager.record_failure(backend.name, f"{type(exc).__name__}: {exc}")
                log.warning(
                    "search backend unexpected error",
                    extra={"backend": backend.name, "query": query, "error": type(exc).__name__},
                )
        return [], failures

    async def _search_all_backends(
        self, query: str, limit: int, safe: bool, region: str
    ) -> tuple[list[SearchResult], dict[str, str]]:
        """Try all backends and merge results, with circuit breaker support."""
        all_results: list[SearchResult] = []
        failures: dict[str, str] = {}

        # Filter backends by health status (skip open circuits)
        available_names = self._health_manager.get_available_backends(
            [b.name for b in self._backends]
        )
        available_backends = [b for b in self._backends if b.name in available_names]

        if not available_backends:
            log.warning("all backends are circuit-broken, trying all anyway")
            available_backends = self._backends

        for backend in available_backends:
            try:
                log.info(
                    "searching (merge mode)", extra={"backend": backend.name, "query": query, "max_results": limit}
                )
                results = await backend.search(query, limit, safe, region)
                if results:
                    all_results.extend(results)
                    self._health_manager.record_success(backend.name)
                    log.info("search succeeded", extra={"backend": backend.name, "query": query, "count": len(results)})
                else:
                    failures[backend.name] = "returned empty results"
                    self._health_manager.record_failure(backend.name, "empty results")
            except SearchError as exc:
                failures[backend.name] = str(exc)
                self._health_manager.record_failure(backend.name, str(exc))
                log.warning("search backend failed", extra={"backend": backend.name, "query": query, "error": str(exc)})
            except Exception as exc:
                failures[backend.name] = f"{type(exc).__name__}: {exc}"
                self._health_manager.record_failure(backend.name, f"{type(exc).__name__}: {exc}")
                log.warning(
                    "search backend unexpected error",
                    extra={"backend": backend.name, "query": query, "error": type(exc).__name__},
                )
        return all_results, failures

    async def search(
        self,
        query: str,
        max_results: int | None = None,
        region: str = "wt-wt",
        safe_search: bool | None = None,
    ) -> list[SearchResult]:
        """Perform a web search with automatic backend failover and result merging."""
        limit = max_results or self.config.search_max_results
        safe = safe_search if safe_search is not None else self.config.search_safe_search
        backend_names = ",".join(b.name for b in self._backends)
        merge_mode = "merge" if self.merge_backends else "single"
        cache_key = f"search:{merge_mode}:{backend_names}:{query}:{limit}:{safe}:{region}"
        if self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                raw = json.loads(cached["value"])
                return [SearchResult(**item) for item in raw]
        if self.merge_backends:
            results, failures = await self._search_all_backends(query, limit, safe, region)
        else:
            results, failures = await self._search_single_backend(query, limit, safe, region)
        if not results:
            raise AllBackendsFailedError(query, failures)
        results = self._deduplicate_results(results)
        results = self._rank_results(results, query)
        results = results[:limit]
        for i, r in enumerate(results, start=1):
            r.position = i
        if self.cache:
            self.cache.set(
                cache_key,
                json.dumps([r.__dict__ for r in results]),
                content_type="application/json",
            )
        log.info(
            "search completed",
            extra={
                "query": query,
                "count": len(results),
                "merge_mode": merge_mode,
                "backends_tried": len(failures) + (1 if results else 0),
            },
        )
        return results
