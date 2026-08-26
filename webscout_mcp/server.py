"""MCP Server implementation for webscout-mcp.

Exposes the following tools to AI agents:

- ``web_search`` — Search the web via Bing.
- ``web_fetch`` — Fetch a single URL and extract main content.
- ``web_crawl`` — Crawl a website with depth/page limits.
- ``web_extract`` — Extract structured data from a page using CSS selectors.
- ``cache_stats`` — Show cache statistics.
- ``cache_clear`` — Clear the cache.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server.mcpserver import MCPServer

from .cache import Cache
from .config import Config
from .crawler import Crawler
from .extractor import DataExtractor, ExtractionRule
from .fetcher import Fetcher
from .search import SearchEngine


def create_server(config: Optional[Config] = None) -> MCPServer:
    """Create and configure the MCP server.

    Args:
        config: Optional Config instance.  If None, loads from environment.

    Returns:
        A configured ``MCPServer`` instance.
    """
    cfg = config or Config.from_env()
    cfg.ensure_dirs()

    cache = Cache(
        db_path=cfg.cache_dir / "webscout.db",
        ttl=cfg.cache_ttl,
        max_size_mb=cfg.cache_max_size_mb,
    )
    fetcher = Fetcher(cfg, cache)
    search_engine = SearchEngine(cfg, cache)
    crawler = Crawler(cfg, fetcher)
    extractor = DataExtractor(cfg, fetcher)

    mcp = MCPServer(
        name="webscout",
        instructions=(
            "Web search and fetch tools for AI agents. "
            "Use web_search to find information, web_fetch to read a specific "
            "page's main content, web_crawl to explore a site, and "
            "web_extract to pull structured data via CSS selectors. "
            "All results are cached locally to avoid redundant requests."
        ),
    )

    # --- web_search ---
    @mcp.tool()
    async def web_search(
        query: str,
        max_results: int = 10,
        region: str = "wt-wt",
        safe_search: bool = True,
    ) -> str:
        """Search the web and return structured results.

        Args:
            query: The search query string.
            max_results: Maximum number of results to return (1-25).
            region: Search region code, e.g. 'wt-wt' (worldwide), 'us-en', 'cn-zh'.
            safe_search: Enable safe search filtering.

        Returns:
            A JSON string with search results including title, url, and snippet.
        """
        max_results = max(1, min(max_results, 25))
        results = await search_engine.search(
            query=query,
            max_results=max_results,
            region=region,
            safe_search=safe_search,
        )
        output = [
            {
                "position": r.position,
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
            }
            for r in results
        ]
        return json.dumps({"query": query, "count": len(output), "results": output}, ensure_ascii=False, indent=2)

    # --- web_fetch ---
    @mcp.tool()
    async def web_fetch(
        url: str,
        extract: bool = True,
        output_format: str = "markdown",
        max_chars: int = 8000,
        bypass_cache: bool = False,
    ) -> str:
        """Fetch a URL and return its content, optionally extracting the main article.

        Args:
            url: The URL to fetch (must start with http:// or https://).
            extract: If true, extract main article content (removes nav, ads, etc.).
            output_format: Output format when extract=true: 'markdown', 'text', or 'html'.
            max_chars: Maximum characters to return (content is truncated beyond this).
            bypass_cache: If true, skip cached version and re-fetch.

        Returns:
            A JSON string with the fetched content, title, status, and metadata.
        """
        result = await fetcher.fetch(
            url=url,
            extract=extract,
            output_format=output_format,
            max_chars=max_chars,
            bypass_cache=bypass_cache,
        )
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)

    # --- web_crawl ---
    @mcp.tool()
    async def web_crawl(
        seed_url: str,
        max_depth: int = 2,
        max_pages: int = 10,
        same_domain_only: bool = True,
        extract: bool = True,
    ) -> str:
        """Crawl a website starting from a seed URL, respecting depth and page limits.

        Args:
            seed_url: The starting URL for the crawl.
            max_depth: Maximum link depth to follow (0 = seed page only).
            max_pages: Maximum number of pages to crawl.
            same_domain_only: If true, only crawl pages on the same domain as seed_url.
            extract: If true, extract main content from each crawled page.

        Returns:
            A JSON string with all crawled pages, their content, and any errors.
        """
        max_depth = max(0, min(max_depth, 5))
        max_pages = max(1, min(max_pages, 50))
        result = await crawler.crawl(
            seed_url=seed_url,
            max_depth=max_depth,
            max_pages=max_pages,
            same_domain_only=same_domain_only,
            extract=extract,
        )
        return json.dumps(result.to_dict(), ensure_ascii=False, indent=2)

    # --- web_extract ---
    @mcp.tool()
    async def web_extract(
        url: str,
        rules: str,
    ) -> str:
        """Extract structured data from a web page using CSS selectors.

        Args:
            url: The URL of the page to extract data from.
            rules: A JSON array of extraction rules. Each rule is an object with:
                - name (required): output key name
                - selector (required): CSS selector string
                - attribute (optional): HTML attribute to extract (e.g. 'href', 'src')
                - multiple (optional): boolean, return list of all matches
                - regex (optional): regex pattern to apply to extracted text
                - default (optional): default value if nothing matches

        Returns:
            A JSON string with the extracted structured data.
        """
        try:
            rules_data = json.loads(rules)
            if not isinstance(rules_data, list):
                return json.dumps({"error": "rules must be a JSON array"}, ensure_ascii=False)
            extraction_rules = [ExtractionRule(**r) for r in rules_data]
        except (json.JSONDecodeError, TypeError) as exc:
            return json.dumps({"error": f"Invalid rules JSON: {exc}"}, ensure_ascii=False)

        result = await extractor.extract_from_url(url, extraction_rules)
        return json.dumps(result, ensure_ascii=False, indent=2)

    # --- cache_stats ---
    @mcp.tool()
    def cache_stats() -> str:
        """Return cache statistics: entry count, total size, TTL, and limits."""
        stats = cache.stats()
        return json.dumps(stats, ensure_ascii=False, indent=2)

    # --- cache_clear ---
    @mcp.tool()
    def cache_clear() -> str:
        """Clear all cached entries. Returns the number of entries deleted."""
        deleted = cache.clear()
        return json.dumps({"cleared": deleted, "status": "ok"}, ensure_ascii=False)

    return mcp
