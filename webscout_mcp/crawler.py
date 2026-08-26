"""Lightweight web crawler with depth and page limits.

Built on top of :class:`Fetcher`.  Performs a BFS crawl starting from a seed
URL, respecting depth, page-count, and same-domain constraints.  Links are
extracted from each page's HTML and normalised before being queued.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .config import Config
from .fetcher import Fetcher, FetchResult
from .utils import normalize_url


@dataclass
class CrawlResult:
    """Result of a crawl operation."""

    seed_url: str
    pages_crawled: int = 0
    pages: list[FetchResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    links_found: int = 0

    def to_dict(self) -> dict:
        return {
            "seed_url": self.seed_url,
            "pages_crawled": self.pages_crawled,
            "links_found": self.links_found,
            "pages": [p.to_dict() for p in self.pages],
            "errors": self.errors,
        }


class Crawler:
    """A polite, bounded web crawler."""

    def __init__(self, config: Config, fetcher: Fetcher):
        self.config = config
        self.fetcher = fetcher

    async def crawl(
        self,
        seed_url: str,
        max_depth: Optional[int] = None,
        max_pages: Optional[int] = None,
        same_domain_only: Optional[bool] = None,
        extract: bool = True,
    ) -> CrawlResult:
        """Crawl a website starting from ``seed_url``.

        Args:
            seed_url: The starting URL.
            max_depth: Maximum link depth (default from config).
            max_pages: Maximum number of pages to crawl (default from config).
            same_domain_only: If True, only crawl pages on the same domain.
            extract: If True, extract main content from each page.

        Returns:
            A ``CrawlResult`` with all crawled pages.
        """
        depth = max_depth if max_depth is not None else self.config.crawler_max_depth
        page_limit = max_pages if max_pages is not None else self.config.crawler_max_pages
        same_domain = same_domain_only if same_domain_only is not None else self.config.crawler_same_domain_only

        seed_url = normalize_url(seed_url)
        seed_domain = urlparse(seed_url).netloc.lower()

        result = CrawlResult(seed_url=seed_url)
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(seed_url, 0)])

        while queue and result.pages_crawled < page_limit:
            url, current_depth = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            # Fetch the page
            page = await self.fetcher.fetch(url, extract=extract, max_chars=4000)
            result.pages_crawled += 1

            if page.error:
                result.errors.append({"url": url, "depth": current_depth, "error": page.error})
                continue

            result.pages.append(page)

            # Don't extract links if at max depth
            if current_depth >= depth:
                continue

            # Extract links
            links = self._extract_links(page.content, url)
            result.links_found += len(links)

            for link in links:
                link = normalize_url(link)
                if link in visited:
                    continue
                if same_domain:
                    link_domain = urlparse(link).netloc.lower()
                    if link_domain != seed_domain:
                        continue
                queue.append((link, current_depth + 1))

        return result

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        """Extract all absolute http(s) links from HTML."""
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
