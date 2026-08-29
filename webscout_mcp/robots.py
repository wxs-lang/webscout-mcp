"""robots.txt compliance checker.

Fetches, parses, and caches robots.txt for each domain. Uses the
standard-library urllib.robotparser under the hood, wrapped for async use
with caching and sensible fallbacks.

When a site's robots.txt cannot be fetched (timeout, 5xx, etc.), the checker
defaults to *allow* and logs a warning - better to crawl than to silently
block everything when a site is temporarily down.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from .config import Config
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class _RobotsEntry:
    parser: RobotFileParser | None = None
    fetched_at: float = 0.0
    failed: bool = False
    crawl_delay: float = 0.0


class RobotsChecker:
    """Async robots.txt checker with per-domain caching."""

    def __init__(
        self,
        config: Config,
        cache_ttl: int = 3600,
        respect_robots: bool = True,
    ) -> None:
        self.config = config
        self.cache_ttl = cache_ttl
        self.respect_robots = respect_robots
        self._cache: dict[str, _RobotsEntry] = {}
        self._client: httpx.AsyncClient | None = None
        self._locks: dict[str, asyncio.Lock] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            client_kwargs: dict = {
                "timeout": httpx.Timeout(self.config.request_timeout),
                "follow_redirects": True,
                "headers": {"User-Agent": self.config.user_agent},
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

    @staticmethod
    def _domain(url: str) -> str:
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc.lower()}"
        except Exception:
            return url

    def _is_fresh(self, entry: _RobotsEntry) -> bool:
        return (time.monotonic() - entry.fetched_at) < self.cache_ttl

    async def _fetch_robots(self, domain: str) -> _RobotsEntry:
        if domain in self._cache and self._is_fresh(self._cache[domain]):
            return self._cache[domain]
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            if domain in self._cache and self._is_fresh(self._cache[domain]):
                return self._cache[domain]
            entry = _RobotsEntry(fetched_at=time.monotonic())
            robots_url = f"{domain}/robots.txt"
            try:
                client = await self._get_client()
                response = await client.get(robots_url)
                if response.status_code == 404:
                    entry.parser = None
                    log.debug("no robots.txt (404)", domain=domain)
                elif response.status_code >= 400:
                    entry.failed = True
                    log.warning("robots.txt fetch failed", domain=domain, status=response.status_code)
                else:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
                    entry.parser = parser
                    try:
                        delay = parser.crawl_delay(self.config.user_agent)
                        if delay:
                            entry.crawl_delay = float(delay)
                    except Exception:
                        pass
                    log.debug("robots.txt parsed", domain=domain, crawl_delay=entry.crawl_delay)
            except Exception as exc:
                entry.failed = True
                log.warning("robots.txt fetch error", domain=domain, error=type(exc).__name__)
            self._cache[domain] = entry
            return entry

    async def is_allowed(self, url: str, user_agent: str | None = None) -> bool:
        if not self.respect_robots:
            return True
        domain = self._domain(url)
        entry = await self._fetch_robots(domain)
        if entry.failed or entry.parser is None:
            return True
        ua = user_agent or self.config.user_agent
        try:
            return entry.parser.can_fetch(ua, url)
        except Exception:
            return True

    async def get_crawl_delay(self, url: str) -> float:
        domain = self._domain(url)
        entry = await self._fetch_robots(domain)
        return entry.crawl_delay

    def clear_cache(self) -> None:
        self._cache.clear()
        log.debug("robots.txt cache cleared")
