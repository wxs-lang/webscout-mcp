"""Concurrent web crawler with depth/page limits and robots.txt compliance.
Performs a BFS crawl starting from a seed URL, fetching pages concurrently
within each depth level. Respects depth, page-count, same-domain, and
robots.txt constraints.
Concurrency is controlled by crawler_concurrency (default 5) via an
asyncio.Semaphore. Each depth level is fetched as a batch before moving to
the next level, preserving BFS ordering.
Enhanced features:
- Configurable random delay between requests to avoid rate limiting
- Automatic retry on transient failures
- Smart link deduplication and filtering
- Progress tracking and statistics
- Graceful error handling with classification
"""

from __future__ import annotations

import asyncio
import random
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
    """Result of a crawl operation."""

    seed_url: str
    pages_crawled: int = 0
    pages: list[FetchResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    links_found: int = 0
    skipped_robots: int = 0
    retries: int = 0
    avg_response_time: float = 0.0

    def to_dict(self) -> dict:
        return {
            "seed_url": self.seed_url,
            "pages_crawled": self.pages_crawled,
            "links_found": self.links_found,
            "skipped_robots": self.skipped_robots,
            "retries": self.retries,
            "avg_response_time": round(self.avg_response_time, 2),
            "pages": [p.to_dict() for p in self.pages],
            "errors": self.errors,
        }


class Crawler:
    """A concurrent, polite, bounded web crawler with retry and delay support."""

    def __init__(
        self,
        config: Config,
        fetcher: Fetcher,
        robots_checker: Optional[RobotsChecker] = None,
    ) -> None:
        self.config = config
        self.fetcher = fetcher
        self.robots = robots_checker or RobotsChecker(config, respect_robots=config.respect_robots)
        self._total_response_time = 0.0
        self._response_count = 0

    async def crawl(
        self,
        seed_url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        same_domain_only: Optional[bool] = None,
        extract: bool = True,
        concurrency: Optional[int] = None,
        delay: Optional[float] = None,
        max_retries: Optional[int] = None,
    ) -> CrawlResult:
        """Crawl a website starting from seed_url.

        Args:
            seed_url: Starting URL.
            max_depth: Maximum crawl depth.
            max_pages: Maximum number of pages to crawl.
            same_domain_only: Only crawl pages on the same domain.
            extract: Whether to extract main content from pages.
            concurrency: Number of concurrent requests.
            delay: Base delay between requests in seconds (randomized 0.5x-1.5x).
            max_retries: Maximum number of retries per page.

        Returns:
            CrawlResult with pages, errors, and statistics.
        """
        depth = max_depth if max_depth is not None else self.config.crawler_max_depth
        page_limit = max_pages if max_pages is not None else self.config.crawler_max_pages
        same_domain = same_domain_only if same_domain_only is not None else self.config.crawler_same_domain_only
        concur = concurrency or self.config.crawler_concurrency
        base_delay = delay if delay is not None else getattr(self.config, "crawler_delay", 0.0)
        retries = max_retries if max_retries is not None else getattr(self.config, "crawler_max_retries", 2)

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
            log.info(
                "crawling depth level",
                extra={"depth": batch[0][1], "batch_size": len(batch), "total_crawled": result.pages_crawled},
            )
            tasks = [self._crawl_page(url, dep, extract, semaphore, result, base_delay, retries) for url, dep in batch]
            page_results = await asyncio.gather(*tasks, return_exceptions=True)
            for (url, dep), pr in zip(batch, page_results):
                if isinstance(pr, Exception):
                    result.errors.append({"url": url, "depth": dep, "error": str(pr), "type": "exception"})
                    continue
                if pr is None:
                    continue
                page, links = pr
                result.pages_crawled += 1
                result.pages.append(page)
                if dep < depth:
                    new_links = self._filter_links(links, visited, same_domain, seed_domain)
                    for link in new_links:
                        next_level.append((link, dep + 1))
            current_level = next_level

        # Calculate average response time
        if self._response_count > 0:
            result.avg_response_time = self._total_response_time / self._response_count

        log.info(
            "crawl complete",
            extra={
                "seed": seed_url,
                "pages": result.pages_crawled,
                "errors": len(result.errors),
                "skipped_robots": result.skipped_robots,
                "retries": result.retries,
            },
        )
        return result

    def _filter_links(
        self,
        links: list[str],
        visited: set[str],
        same_domain: bool,
        seed_domain: str,
    ) -> list[str]:
        """Filter and deduplicate links."""
        filtered: list[str] = []
        seen: set[str] = set()
        for link in links:
            link = normalize_url(link)
            if link in visited or link in seen:
                continue
            if same_domain:
                link_domain = urlparse(link).netloc.lower()
                if link_domain != seed_domain:
                    continue
            # Skip common non-content URLs
            parsed = urlparse(link)
            if parsed.path.endswith((".pdf", ".zip", ".tar", ".gz", ".exe", ".dmg", ".mp4", ".mp3", ".avi", ".mov")):
                continue
            if any(skip in parsed.path.lower() for skip in ["/login", "/signup", "/register", "/admin", "/logout"]):
                continue
            seen.add(link)
            filtered.append(link)
        return filtered

    async def _crawl_page(
        self,
        url: str,
        depth: int,
        extract: bool,
        semaphore: asyncio.Semaphore,
        result: CrawlResult,
        base_delay: float,
        max_retries: int,
    ) -> Optional[tuple[FetchResult, list[str]]]:
        """Crawl a single page with retry support."""
        if self.config.respect_robots:
            try:
                allowed = await self.robots.is_allowed(url)
                if not allowed:
                    result.skipped_robots += 1
                    log.debug("skipped by robots.txt", extra={"url": url})
                    return None
            except Exception as exc:
                log.warning("robots.txt check failed, allowing", extra={"url": url, "error": str(exc)})

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                # Apply random delay
                if base_delay > 0 and attempt > 0:
                    delay = base_delay * random.uniform(0.5, 1.5) * (2**attempt)
                    await asyncio.sleep(delay)
                elif base_delay > 0:
                    delay = base_delay * random.uniform(0.5, 1.5)
                    await asyncio.sleep(delay)

                async with semaphore:
                    import time

                    start_time = time.time()
                    page = await self.fetcher.fetch(url, extract=extract, max_chars=4000)
                    elapsed = time.time() - start_time
                    self._total_response_time += elapsed
                    self._response_count += 1

                if page.error:
                    # Classify error
                    error_type = self._classify_error(page.error)
                    if error_type == "transient" and attempt < max_retries:
                        result.retries += 1
                        last_error = page.error
                        continue
                    result.errors.append(
                        {
                            "url": url,
                            "depth": depth,
                            "error": page.error,
                            "type": error_type,
                            "attempts": attempt + 1,
                        }
                    )
                    return None

                links: list[str] = []
                try:
                    if page.raw_html:
                        links = self._extract_links(page.raw_html, url)
                        result.links_found += len(links)
                except Exception:
                    pass
                return page, links

            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    result.retries += 1
                    continue
                result.errors.append(
                    {
                        "url": url,
                        "depth": depth,
                        "error": str(exc),
                        "type": "exception",
                        "attempts": attempt + 1,
                    }
                )
                return None

        if last_error:
            result.errors.append(
                {
                    "url": url,
                    "depth": depth,
                    "error": last_error,
                    "type": "exhausted_retries",
                    "attempts": max_retries + 1,
                }
            )
        return None

    @staticmethod
    def _classify_error(error: str) -> str:
        """Classify an error as transient or permanent."""
        error_lower = error.lower()
        transient_keywords = [
            "timeout",
            "timed out",
            "connection",
            "reset",
            "refused",
            "500",
            "502",
            "503",
            "504",
            "temporarily",
            "rate limit",
            "too many requests",
            "server error",
            "network",
        ]
        for keyword in transient_keywords:
            if keyword in error_lower:
                return "transient"
        return "permanent"

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        """Extract all valid HTTP/HTTPS links from HTML."""
        links: list[str] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
                    continue
                absolute = urljoin(base_url, href)
                parsed = urlparse(absolute)
                if parsed.scheme in ("http", "https"):
                    # Remove fragment
                    clean_url = absolute.split("#")[0]
                    if clean_url:
                        links.append(clean_url)
        except Exception:
            pass
        return links
