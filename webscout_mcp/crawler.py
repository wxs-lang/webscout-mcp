"""Concurrent web crawler with depth/page limits and robots.txt compliance.

Performs a BFS crawl starting from a seed URL, fetching pages concurrently
within each depth level. Respects depth, page-count, same-domain, and
robots.txt constraints.

Concurrency is controlled by crawler_concurrency (default 5) via an
asyncio.Semaphore. Each depth level is fetched as a batch before moving to
the next level, preserving BFS ordering.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .config import Config
from .exceptions import DisallowedByRobotsError
from .fetcher import Fetcher, FetchResult
from .logging import get_logger
from .robots import RobotsChecker
from .utils import normalize_url

log = get_logger(__name__)


@dataclass
class CrawlResult:
    seed_url: str
    pages_crawled: int = 0
    pages: list[FetchResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    links_found: int = 0
    skipped_robots: int = 0

    def to_dict(self) -> dict:
        return {
            "seed_url": self.seed_url,
            "pages_crawled": self.pages_crawled,
            "links_found": self.links_found,
            "skipped_robots": self.skipped_robots,
            "pages": [p.to_dict() for p in self.pages],
            "errors": self.errors,
        }


class Crawler:
    """A concurrent, polite, bounded web crawler."""

    def __init__(
        self,
        config: Config,
        fetcher: Fetcher,
        robots_checker: Optional[RobotsChecker] = None,
    ) -> None:
        self.config = config
        self.fetcher = fetcher
        self.robots = robots_checker or RobotsChecker(
            config, respect_robots=config.respect_robots
        )

    async def crawl(
        self,
        seed_url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        same_domain_only: Optional[bool] = None,
        extract: bool = True,
        concurrency: Optional[int] = None,
    ) -> CrawlResult:
        depth = max_depth if max_depth is not None else self.config.crawler_max_depth
        page_limit = max_pages if max_pages is not None else self.config.crawler_max_pages
        same_domain = (
            same_domain_only
            if same_domain_only is not None
            else self.config.crawler_same_domain_only
        )
        concur = concurrency or self.config.crawler_concurrency
        seed_url = normalize_url(seed_url)
        seed_domain = urlparse(seed_url).netloc.lower()

        result = CrawlResult(seed_url=seed_url)
        visited: set[str] = set()
        semaphore = asyncio.Semaphore(concur)

        current_level: deque[tuple[str, int]] = deque([(seed_url, 0)])
        while current_level and result.pages_crawled < page_limit:
            next_level: deque[tuple[str, int]] = deque()
            batch: list[tuple[str, int]] = []
            while current_level and len(batch) < (page_limit - result.pages_crawled):
                url, dep = current_level.popleft()
                if url in visited:
                    continue
                visited.add(url)
                batch.append((url, dep))
            if not batch:
                break

            log.info("crawling depth level", depth=batch[0][1], batch_size=len(batch), total_crawled=result.pages_crawled)
            tasks = [
                self._crawl_page(url, dep, extract, semaphore, result)
                for url, dep in batch
            ]
            page_results = await asyncio.gather(*tasks, return_exceptions=True)

            for (url, dep), pr in zip(batch, page_results):
                if isinstance(pr, Exception):
                    result.errors.append({"url": url, "depth": dep, "error": str(pr)})
                    continue
                if pr is None:
                    continue
                page, links = pr
                result.pages_crawled += 1
                result.pages.append(page)
                if dep < depth:
                    for link in links:
                        link = normalize_url(link)
                        if link in visited:
                            continue
                        if same_domain:
                            link_domain = urlparse(link).netloc.lower()
                            if link_domain != seed_domain:
                                continue
                        next_level.append((link, dep + 1))
            current_level = next_level

        log.info("crawl complete", seed=seed_url, pages=result.pages_crawled, errors=len(result.errors), skipped_robots=result.skipped_robots)
        return result

    async def _crawl_page(
        self,
        url: str,
        depth: int,
        extract: bool,
        semaphore: asyncio.Semaphore,
        result: CrawlResult,
    ) -> Optional[tuple[FetchResult, list[str]]]:
        if self.config.respect_robots:
            try:
                allowed = await self.robots.is_allowed(url)
                if not allowed:
                    result.skipped_robots += 1
                    log.debug("skipped by robots.txt", url=url)
                    return None
            except Exception as exc:
                log.warning("robots.txt check failed, allowing", url=url, error=str(exc))

        async with semaphore:
            page = await self.fetcher.fetch(url, extract=extract, max_chars=4000)

        if page.error:
            result.errors.append({"url": url, "depth": depth, "error": page.error})
            return None

        links: list[str] = []
        try:
            if page.raw_html:
                links = self._extract_links(page.raw_html, url)
                result.links_found += len(links)
        except Exception:
            pass
        return page, links

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        links: list[str] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                absolute = urljoin(base_url, href)
                parsed = urlparse(absolute)
                if parsed.scheme in ("http", "https"):
                    links.append(absolute)
        except Exception:
            pass
        return links
