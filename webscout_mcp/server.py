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
                capabilities={ProviderCapability.FETCH},
                cost_tier=ProviderCostTier.PAID,
                description="Crawl4AI browser render sidecar (escalation only)",
            )
            log.info("Crawl4AI browser sidecar registered at %s", browser_backend.base_url)
        except Exception as e:  # pragma: no cover - defensive
            log.warning(f"Could not register Crawl4AI backend: {e}")
    else:
        log.info("Crawl4AI sidecar not configured; web_fetch uses fast path only")

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

        Uses Bing first, automatically falls back to DuckDuckGo HTML if Bing
        fails or returns nothing. No API key required.
        """
        max_results = max(1, min(max_results, 25))
        from .search_provider import SearchRequest

        # Try new SearchService first, fall back to old SearchEngine
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
                else:
                    # Fall back to old SearchEngine
                    log.warning(
                        "SearchService returned error, falling back to SearchEngine",
                        extra={"error": response.error_message},
                    )
                    results = await search_engine.search(
                        query=query,
                        max_results=max_results,
                        region=region,
                        safe_search=safe_search,
                    )
            except Exception as exc:
                log.warning(
                    "SearchService failed, falling back to SearchEngine",
                    extra={"error": str(exc)},
                )
                results = await search_engine.search(
                    query=query,
                    max_results=max_results,
                    region=region,
                    safe_search=safe_search,
                )
        else:
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
        from .fetch_escalation import should_escalate_to_browser
        from .fetch_provider import FetchRequest
        from .observability import record_escalation, record_fetch_attempt

        result = await fetcher.fetch(
            url=url,
            extract=extract,
            output_format=output_format,
            max_chars=max_chars,
            bypass_cache=bypass_cache,
        )
        out = result.to_dict()

        # Observability: classify the fast-http attempt.
        try:
            status = out.get("status_code", 0) or 0
            if out.get("error"):
                if status in (401, 403, 451):
                    fast_result = "forbidden"
                elif "timeout" in (out.get("error") or "").lower():
                    fast_result = "timeout"
                else:
                    fast_result = "failure"
            elif status >= 400:
                fast_result = "forbidden" if status in (401, 403, 451) else "failure"
            else:
                fast_result = "success"
            record_fetch_attempt(
                "fast-http",
                result=fast_result,
                latency_ms=float(out.get("latency_ms", 0.0)),
            )
        except Exception:  # pragma: no cover - observability must not break fetch
            log.exception("observability record fast-http failed")

        # Escalation path: only when the fast fetch looks inadequate AND a
        # browser sidecar is configured. We never replace the original
        # response — on browser failure we keep the fast-fetch result and
        # annotate it so the caller can see what happened.
        if browser_backend.is_available:
            from .fetch_provider import FetchResponse

            fast_resp = FetchResponse.from_fetch_result(result, provider="http", latency_ms=0.0)
            decision = should_escalate_to_browser(fast_resp)
            out["escalation"] = decision.to_dict()
            if decision.escalate:
                try:
                    record_escalation(decision.reason_code.value if decision.reason_code else "unknown")
                except Exception:  # pragma: no cover
                    log.exception("observability record_escalation failed")
                try:
                    browser_resp = await browser_backend.fetch(
                        FetchRequest(
                            url=url,
                            extract=extract,
                            output_format=output_format,
                            max_chars=max_chars,
                            bypass_cache=bypass_cache,
                        )
                    )
                    out["browser_attempted"] = True
                    out["browser_backend"] = "crawl4ai"
                    out["browser_reason"] = decision.reason_code.value if decision.reason_code else None
                    if browser_resp.is_success and browser_resp.content:
                        # Browser succeeded: prefer its rendered content, but keep
                        # the fast-fetch metadata for transparency.
                        out["content"] = browser_resp.content[:max_chars]
                        out["title"] = browser_resp.title or out.get("title", "")
                        out["extracted"] = True
                        out["browser_success"] = True
                    else:
                        out["browser_success"] = False
                        out["browser_error"] = browser_resp.error
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("Crawl4AI escalation failed for %s: %s", url, exc)
                    out["browser_attempted"] = True
                    out["browser_success"] = False
                    out["browser_error"] = f"{type(exc).__name__}: {exc}"
                out.setdefault("browser_success", False)

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
            "fallback_engine_enabled": search_service is not None,
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
