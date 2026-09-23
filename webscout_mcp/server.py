"""MCP Server implementation for webscout-mcp.

Exposes the following tools to AI agents:

Core Web Tools:
- ``web_search`` - Search the web (Bing + DuckDuckGo failover, no API key).
- ``web_fetch`` - Fetch a single URL and extract main content.
- ``web_crawl`` - Crawl a website with depth/page limits (concurrent).
- ``web_extract`` - Extract structured data from a page using CSS selectors.

Cache Management:
- ``cache_stats`` - Show cache statistics.
- ``cache_clear`` - Clear the cache.

Health & Monitoring:
- ``search_health`` - Get health report for all search backends (circuit breaker status).

Content Analysis:
- ``metadata_extract`` - Extract page metadata (JSON-LD, OpenGraph, Twitter Cards).
- ``rss_parse`` - Parse RSS/Atom feeds and return entries.
- ``content_quality`` - Analyze content quality (readability, keyword density, structure).
- ``broken_links`` - Check for broken links on a web page.
"""

from __future__ import annotations

import asyncio
import json

# MCP compatibility: support both 1.x (FastMCP) and 2.x (MCPServer)
try:
    # MCP 2.x: FastMCP was renamed to MCPServer
    from mcp.server.mcpserver import MCPServer
except ImportError:
    # MCP 1.x: use FastMCP
    from mcp.server.fastmcp import FastMCP as MCPServer

from .cache import Cache
from .config import Config
from .content_quality import ContentQualityAnalyzer
from .crawler import Crawler
from .extractor import DataExtractor, ExtractionRule
from .fetcher import Fetcher
from .logging_config import get_logger, setup_logging
from .metadata_extractor import MetadataExtractor
from .robots import RobotsChecker
from .rss_parser import fetch_and_parse_feed
from .search import SearchEngine
from .search_service import create_search_service_from_config
from .startup_check import StartupSelfCheck

log = get_logger(__name__)

# Global startup check instance (initialized in create_server)
_startup_check: StartupSelfCheck | None = None
_startup_task: asyncio.Task | None = None


def _schedule_startup_check() -> None:
    """Schedule the startup self-check on the current running loop (if any).

    create_server() is normally called from inside asyncio.run() (see
    __main__._cmd_serve), so the loop is running and the task executes.
    When called from a synchronous context (e.g. some tests), we skip the
    check instead of leaking an unawaited coroutine, which previously
    produced: RuntimeWarning: coroutine 'StartupSelfCheck.run_all' was
    never awaited.
    """
    global _startup_task
    if _startup_check is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("No running event loop; startup self-check deferred")
        return
    _startup_task = loop.create_task(_startup_check.run_all())


def create_server(config: Config | None = None) -> MCPServer:
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

    # Provider registry: single source of truth for provider state.
    # Search providers are registered by the factory; the HTTP fetch
    # provider is registered here since it wraps this server's fetcher.
    from .fetch_provider import HTTPFetchProvider
    from .provider_registry import ProviderRegistry
    from .provider_router import ProviderCapability, ProviderCostTier

    registry = ProviderRegistry()
    try:
        search_service = create_search_service_from_config(cfg, cache, registry=registry)
        log.info("SearchService initialized with new SearchProvider architecture")
    except Exception as e:
        log.warning(f"Could not initialize SearchService, falling back to SearchEngine: {e}")
        search_service = None
    try:
        registry.register(
            HTTPFetchProvider(fetcher),
            capabilities={ProviderCapability.FETCH},
            cost_tier=ProviderCostTier.FREE,
            description="HTTP fetch provider (smart Fetcher)",
        )
    except Exception as e:  # pragma: no cover - defensive
        log.warning(f"Could not register HTTP fetch provider: {e}")

    # Optional browser-fetch sidecar (Crawl4AI). Wired in only when
    # CRAWL4AI_BASE_URL + CRAWL4AI_ENABLED are set; otherwise the
    # web_fetch fast path is unchanged from v1.2.1.
    from .crawl4ai_backend import Crawl4AIBrowserBackend

    browser_backend = Crawl4AIBrowserBackend(cfg)
    if browser_backend.is_available:
        try:
            registry.register(
                browser_backend,
                capabilities={ProviderCapability.BROWSER},
                cost_tier=ProviderCostTier.PAID,
                description="Crawl4AI browser render sidecar (escalation only, BROWSER capability)",
            )
            log.info("Crawl4AI browser sidecar registered at %s", browser_backend.base_url)
        except Exception as e:  # pragma: no cover - defensive
            log.warning(f"Could not register Crawl4AI backend: {e}")
    else:
        log.info("Crawl4AI sidecar not configured; web_fetch uses fast path only")

    # Phase 2: FetchService owns fast-fetch selection + browser escalation.
    # server.py no longer makes routing decisions.
    from .fetch_service import FetchService

    fetch_service = FetchService(registry=registry, config=cfg)

    robots_checker = RobotsChecker(cfg, respect_robots=cfg.respect_robots)
    crawler = Crawler(cfg, fetcher, robots_checker)
    extractor = DataExtractor(cfg, fetcher)
    metadata_extractor = MetadataExtractor()
    content_quality_analyzer = ContentQualityAnalyzer()

    # Initialize startup self-check
    global _startup_check
    _startup_check = StartupSelfCheck(
        search_engine=search_engine,
        search_service=search_service,
        fetcher=fetcher,
        cache=cache,
    )
    # Run startup check in background (non-blocking; safe in sync contexts)
    _schedule_startup_check()

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

        SearchService uses health-based provider ranking, deterministic
        recovery classification, and automatic fallback across registered
        search providers. Empty/invalid queries are rejected without network
        calls. No API key required for the default HTML providers.
        """
        max_results = max(1, min(max_results, 25))
        from .search_provider import SearchRequest

        # Phase 3 cutover: SearchService is the sole production authority when
        # initialized. EMPTY / ERROR / STOP are final outcomes — we do NOT call
        # legacy SearchEngine a second time. Legacy is only a startup fallback
        # when search_service is None.
        if search_service is not None:
            try:
                request = SearchRequest(
                    query=query,
                    max_results=max_results,
                    region=region,
                    safe_search=safe_search,
                )
                response = await search_service.search(request)
                if response.is_success:
                    results = response.results
                    status = "success"
                    error_block = None
                elif response.is_empty:
                    results = []
                    status = "empty"
                    error_block = None
                else:
                    results = []
                    status = "error"
                    error_block = {
                        "code": getattr(response.error_type, "value", "SEARCH_BACKEND_FAILED"),
                        "message": response.error_message or "Search failed",
                        "retryable": bool(response.retryable),
                    }
            except Exception as exc:  # noqa: BLE001
                # Unexpected SearchService failure: safe error response, no
                # legacy second search, no traceback / credential leakage.
                log.warning("SearchService raised unexpected error", extra={"error": str(exc)})
                results = []
                status = "error"
                error_block = {
                    "code": "SYSTEM_ERROR",
                    "message": "Search service encountered an unexpected error",
                    "retryable": True,
                }
        else:
            # Startup-level legacy fallback only.
            results = await search_engine.search(
                query=query,
                max_results=max_results,
                region=region,
                safe_search=safe_search,
            )
            status = "success" if results else "empty"
            error_block = None

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
        payload = {
            "query": query,
            "count": len(output),
            "results": output,
            "status": status,
        }
        if error_block is not None:
            payload["error"] = error_block
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @mcp.tool()
    async def web_fetch(
        url: str,
        extract: bool = True,
        output_format: str = "markdown",
        max_chars: int = 8000,
        bypass_cache: bool = False,
        start_char: int = 0,
    ) -> str:
        """Fetch a URL and return one window of its extracted main content.

        Progressive delivery: each call returns at most ``max_chars`` chars
        (default 8000). If the response contains ``continuation.has_more=true``,
        more content is available locally. To read the next window, call this
        SAME tool again with the SAME url/extract/output_format/max_chars and set
        ``start_char`` to the previous ``continuation.next_start_char``. Follow-up
        windows are served from a local snapshot (no new HTTP fetch, extraction,
        or browser). Stop when ``has_more`` is false. You do not need to read the
        whole page unless the task requires it.
        """
        from .fetch_provider import FetchRequest

        route = await fetch_service.fetch(
            FetchRequest(
                url=url,
                extract=extract,
                output_format=output_format,
                max_chars=max_chars,
                bypass_cache=bypass_cache,
                start_char=start_char,
            )
        )
        out = route.legacy_out(max_chars=max_chars)
        return json.dumps(out, ensure_ascii=False, indent=2)

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

    @mcp.tool()
    def search_health() -> str:
        """Get health report for all search backends.

        Returns overall health score, per-backend status (healthy/degraded/open/half-open),
        circuit breaker state, and request statistics. Use this to diagnose search failures.

        Reports the active SearchService health first, with legacy SearchEngine
        health included as fallback reference during the migration period.
        """
        # Build unified health report
        unified_report: dict = {
            "active_search_path": "SearchService" if search_service is not None else "SearchEngine (legacy)",
            # Legacy engine is ONLY a startup fallback when SearchService failed
            # to initialize. It is never invoked per-request after Phase 3.
            "legacy_engine_runtime_fallback": search_service is None,
        }

        # Primary: SearchService health (the actual active search path)
        if search_service is not None:
            try:
                service_report = search_service.get_health_report()
                unified_report["search_service"] = service_report
            except Exception as exc:
                unified_report["search_service"] = {"error": f"Failed to get service health: {exc}"}

        # Secondary: legacy SearchEngine health (fallback reference)
        try:
            engine_report = search_engine.get_health_report()
            unified_report["legacy_engine"] = engine_report
        except Exception as exc:
            unified_report["legacy_engine"] = {"error": f"Failed to get engine health: {exc}"}

        # Provider registry overview (registered providers + health, v1.2.0)
        try:
            unified_report["provider_registry"] = registry.health_report()
        except Exception as exc:
            unified_report["provider_registry"] = {"error": f"Failed to get registry health: {exc}"}

        # Include startup self-check report if available
        if _startup_check is not None and _startup_check.report is not None:
            unified_report["startup_check"] = _startup_check.report.to_dict()
        else:
            unified_report["startup_check"] = {
                "status": "not_run_yet",
                "message": "Startup check still running or not initialized",
            }

        return json.dumps(unified_report, ensure_ascii=False, indent=2, default=str)

    @mcp.tool()
    async def metadata_extract(url: str) -> str:
        """Extract metadata from a web page.

        Extracts JSON-LD, OpenGraph, Twitter Cards, article metadata,
        images, links, and other structured metadata from the page.
        """
        try:
            result = await fetcher.fetch(url=url, extract=False, output_format="html", max_chars=200000)
            html = result.content if hasattr(result, "content") else result.raw_html
            if not html:
                return json.dumps({"error": "Failed to fetch page content", "url": url}, ensure_ascii=False)
            metadata = metadata_extractor.extract(html, base_url=url)
            return json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("metadata_extract failed", extra={"url": url, "error": str(exc)})
            return json.dumps({"error": f"Metadata extraction failed: {exc}", "url": url}, ensure_ascii=False)

    @mcp.tool()
    async def rss_parse(url: str, max_entries: int = 20) -> str:
        """Parse an RSS or Atom feed and return its entries.

        Fetches and parses RSS 2.0, RSS 1.0, and Atom feeds. Returns feed title,
        description, link, and a list of entries with title, link, description,
        publication date, and author.
        """
        max_entries = max(1, min(max_entries, 100))
        try:
            feed = await fetch_and_parse_feed(url, max_entries=max_entries)
            return json.dumps(feed.to_dict(), ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("rss_parse failed", extra={"url": url, "error": str(exc)})
            return json.dumps({"error": f"RSS parsing failed: {exc}", "url": url}, ensure_ascii=False)

    @mcp.tool()
    async def content_quality(url: str) -> str:
        """Analyze content quality of a web page.

        Evaluates readability scores (Flesch-Kincaid, Gunning Fog),
        keyword density, content structure, metadata quality, and provides
        actionable suggestions for improvement.
        """
        try:
            # Fetch page content
            result = await fetcher.fetch(url=url, extract=True, output_format="text", max_chars=50000)
            text = result.content if hasattr(result, "content") else result.text
            html_result = await fetcher.fetch(url=url, extract=False, output_format="html", max_chars=200000)
            html = html_result.content if hasattr(html_result, "content") else html_result.raw_html

            if not text:
                return json.dumps({"error": "Failed to fetch page content", "url": url}, ensure_ascii=False)

            # Analyze content quality
            metrics = content_quality_analyzer.analyze(text, html=html or "")
            return json.dumps(metrics.to_dict(), ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("content_quality failed", extra={"url": url, "error": str(exc)})
            return json.dumps({"error": f"Content quality analysis failed: {exc}", "url": url}, ensure_ascii=False)

    @mcp.tool()
    async def broken_links(url: str, timeout: float = 10.0) -> str:
        """Check for broken links on a web page.

        Extracts all links from the page, checks each one's HTTP status,
        and returns a report with broken links, redirects, and link statistics.
        """
        try:
            from .broken_link_checker import BrokenLinkChecker

            # Fetch page HTML
            result = await fetcher.fetch(url=url, extract=False, output_format="html", max_chars=200000)
            html = result.content if hasattr(result, "content") else result.raw_html

            if not html:
                return json.dumps({"error": "Failed to fetch page content", "url": url}, ensure_ascii=False)

            # Check broken links
            checker = BrokenLinkChecker(timeout=timeout)
            report = checker.check_page(html, base_url=url)
            return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("broken_links failed", extra={"url": url, "error": str(exc)})
            return json.dumps({"error": f"Broken link check failed: {exc}", "url": url}, ensure_ascii=False)

    return mcp
