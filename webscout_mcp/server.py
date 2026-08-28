"""MCP Server implementation for webscout-mcp.

Exposes the following tools to AI agents:

- ``web_search`` - Search the web (Bing + DuckDuckGo failover, no API key).
- ``web_fetch`` - Fetch a single URL and extract main content.
- ``web_crawl`` - Crawl a website with depth/page limits (concurrent).
- ``web_extract`` - Extract structured data from a page using CSS selectors.
- ``cache_stats`` - Show cache statistics.
- ``cache_clear`` - Clear the cache.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from .cache import Cache
from .config import Config
from .crawler import Crawler
from .extractor import DataExtractor, ExtractionRule
from .fetcher import Fetcher
from .logging import get_logger, setup_logging
from .robots import RobotsChecker
from .search import SearchEngine

log = get_logger(__name__)


def create_server(config: Optional[Config] = None) -> MCPServer:
    """Create and configure the MCP server."""
    setup_logging()
    cfg = config or Config.from_env()
    cfg.ensure_dirs()

    cache = Cache(
        db_path=cfg.cache_dir / "webscout.db",
        ttl=cfg.cache_ttl,
        max_size_mb=cfg.cache_max_size_mb,
    )
    fetcher = Fetcher(cfg, cache)
    search_engine = SearchEngine(cfg, cache)
    robots_checker = RobotsChecker(cfg, respect_robots=cfg.respect_robots)
    crawler = Crawler(cfg, fetcher, robots_checker)
    extractor = DataExtractor(cfg, fetcher)

    mcp = MCPServer(
        name="webscout",
        instructions=(
            "Web search and fetch tools for AI agents. "
            "Use web_search to find information (Bing + DuckDuckGo failover), "
            "web_fetch to read a specific page's main content, "
            "web_crawl to explore a site concurrently, and "
            "web_extract to pull structured data via CSS selectors. "
            "All results are cached locally to avoid redundant requests. "
            "Crawler respects robots.txt by default."
        ),
    )

    @mcp.tool()
    async def web_search(
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",
        safe_search: bool = True,
    ) -> str:
        """Search the web and return structured results.

        Uses Bing first, automatically falls back to DuckDuckGo HTML if Bing
        fails or returns nothing. No API key required.
        """
        max_results = max(1, min(max_results, 25))
        try:
            results = await search_engine.search(
                query=query,
                max_results=max_results,
                region=region,
                safe_search=safe_search,
            )
        except Exception as exc:
            log.error("web_search failed", extra={"query": query, "error": str(exc)})
            return json.dumps(
                {"error": f"Search failed: {exc}", "query": query},
                ensure_ascii=False,
                indent=2,
            )
        output = [
            {
                "position": r.position,
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "backend": r.backend,
            }
            for r in results
        ]
        return json.dumps(
            {"query": query, "count": len(output), "results": output},
            ensure_ascii=False,
            indent=2,
        )

    @mcp.tool()
    async def web_fetch(
        url: str,
        extract: bool = True,
        output_format: str = "markdown",
        max_chars: int = 8000,
        bypass_cache: bool = False,
    ) -> str:
        """Fetch a URL and return its content, optionally extracting the main article."""
        result = await fetcher.fetch(
            url=url,
            extract=extract,
            output_format=output_format,
            max_chars=max_chars,
            bypass_cache=bypass_cache,
        )
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)

    @mcp.tool()
    async def web_crawl(
        seed_url: str,
        max_depth: int = 2,
        max_pages: int = 10,
        same_domain_only: bool = True,
        extract: bool = True,
        concurrency: int = 5,
    ) -> str:
        """Crawl a website starting from a seed URL, respecting depth and page limits.

        Fetches pages concurrently within each depth level. Respects robots.txt
        by default.
        """
        max_depth = max(0, min(max_depth, 5))
        max_pages = max(1, min(max_pages, 50))
        concurrency = max(1, min(concurrency, 20))
        result = await crawler.crawl(
            seed_url=seed_url,
            max_depth=max_depth,
            max_pages=max_pages,
            same_domain_only=same_domain_only,
            extract=extract,
            concurrency=concurrency,
        )
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)

    @mcp.tool()
    async def web_extract(url: str, rules: str) -> str:
        """Extract structured data from a web page using CSS selectors."""
        try:
            rules_data = json.loads(rules)
            if not isinstance(rules_data, list):
                return json.dumps({"error": "rules must be a JSON array"}, ensure_ascii=False)
            extraction_rules = [ExtractionRule(**r) for r in rules_data]
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps({"error": f"Invalid rules JSON: {exc}"}, ensure_ascii=False)
        result = await extractor.extract_from_url(url, extraction_rules)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool()
    def cache_stats() -> str:
        """Return cache statistics: entry count, total size, TTL, and limits."""
        stats = cache.stats()
        return json.dumps(stats, ensure_ascii=False, indent=2)

    @mcp.tool()
    def cache_clear() -> str:
        """Clear all cached entries. Returns the number of entries deleted."""
        deleted = cache.clear()
        log.info("cache cleared", entries=deleted)
        return json.dumps({"cleared": deleted, "status": "ok"}, ensure_ascii=False)

    return mcp
