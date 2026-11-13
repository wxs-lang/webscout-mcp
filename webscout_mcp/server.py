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

Content Understanding:
- ``web_knowledge_graph`` - Build a knowledge graph of entities and relationships.
- ``web_rag_context`` - Retrieve the passages most relevant to a query, compressed.
- ``web_compare_sites`` - Compare several sites on SEO, performance, content and links.
- ``web_monitor`` - Check a URL for changes since the last check.
"""

from __future__ import annotations

import asyncio
import json
import re

# MCP compatibility: support both 1.x (FastMCP) and 2.x (MCPServer)
try:
    # MCP 2.x: FastMCP was renamed to MCPServer
    from mcp.server.mcpserver import MCPServer
except ImportError:
    # MCP 1.x: use FastMCP
    from mcp.server.fastmcp import FastMCP as MCPServer

from .core.cache import Cache
from .core.config import Config
from .crawler import Crawler
from .extractor import DataExtractor, ExtractionRule
from .extras.content_quality import ContentQualityAnalyzer
from .fetcher import Fetcher
from .logging_config import get_logger, setup_logging
from .metadata_extractor import MetadataExtractor
from .robots import RobotsChecker
from .rss_parser import fetch_and_parse_feed
from .schema_extractor import extract_by_schema
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
    # Dedicated fetcher for metadata_extract with SSRF safety enabled on
    # every request (including redirect hops). The shared `fetcher` keeps
    # its default (safety off) so web_fetch behavior is unchanged.
    metadata_fetcher = Fetcher(cfg, cache)
    metadata_fetcher.safety_check_enabled = True
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
    browser_registered = False
    if browser_backend.is_available:
        try:
            registry.register(
                browser_backend,
                capabilities={ProviderCapability.BROWSER},
                cost_tier=ProviderCostTier.PAID,
                description="Crawl4AI browser render sidecar (escalation only, BROWSER capability)",
            )
            log.info("Crawl4AI browser sidecar registered at %s", browser_backend.base_url)
            browser_registered = True
        except Exception as e:  # pragma: no cover - defensive
            log.warning(f"Could not register Crawl4AI backend: {e}")

    if not browser_registered:
        # No sidecar. Fall back to the browser playwright already gives us via
        # the [browser] extra. Without this the only escalation target was a
        # Docker container, and measured real-world usability stayed at 8/16.
        try:
            from .local_browser_backend import LocalBrowserBackend

            local_backend = LocalBrowserBackend()
            if local_backend.is_available:
                registry.register(
                    local_backend,
                    capabilities={ProviderCapability.BROWSER},
                    cost_tier=ProviderCostTier.FREE,
                    description="Local playwright browser (escalation only, BROWSER capability)",
                )
                log.info(
                    "Local browser registered (playwright); escalation available "
                    "without a sidecar. Requires `playwright install chromium`."
                )
            else:
                log.info(
                    "No browser escalation: Crawl4AI sidecar not configured and the "
                    "playwright dependency is missing. Install with "
                    "`pip install 'webscout-mcp[browser]'` then `playwright install chromium`."
                )
        except Exception as e:  # pragma: no cover - defensive
            log.warning(f"Could not register local browser backend: {e}")

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

        from .search import _is_sponsored

        output = [
            {
                "position": r.position,
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "backend": r.backend,
                # Measured: 2 of 48 results across six queries were paid placements served
                # through an ad redirect, with titles indistinguishable from organic answers.
                # Flagged rather than filtered - a caller can decide about a sponsored result,
                # but not about one it was never told was sponsored.
                "sponsored": _is_sponsored(r.url),
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
    async def web_extract_schema(url: str, schema: str) -> str:
        """Extract data matching a JSON Schema without writing selectors.

        Pass the shape you want and get back an object; no CSS rules, no LLM key. Each field
        is resolved from the best available source, tried in this order:

        1. `json-ld`  - the page's own structured data, so nothing is guessed
        2. `meta`     - OpenGraph / Twitter cards
        3. `semantic-html` - h1, <time>, itemprop, and a few class-name hints

        The response records `sources` per field, so a caller can tell a stated value from an
        inferred one, and lists `missing` fields explicitly rather than leaving silent nulls.

        Use `web_extract` instead when you already know the page's selectors: it is exact,
        whereas this infers. A field whose structure this has never seen comes back null -
        it will not invent a plausible value.

        `schema` is JSON: {"type": "object", "properties": {"price": {"type": "number"}}}.
        """
        try:
            parsed = json.loads(schema)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid schema JSON: {exc}"}, ensure_ascii=False)
        if not isinstance(parsed, dict):
            return json.dumps({"error": "schema must be a JSON object"}, ensure_ascii=False)
        if not isinstance(parsed.get("properties"), dict) or not parsed["properties"]:
            return json.dumps({"error": 'schema needs a non-empty "properties" object'}, ensure_ascii=False)

        try:
            result = await metadata_fetcher.fetch(url=url, extract=False, output_format="html", max_chars=2_000_000)
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller below
            log.error("web_extract_schema fetch failed", extra={"url": url, "error": str(exc)})
            return json.dumps({"error": f"Fetch failed: {exc}", "url": url}, ensure_ascii=False)

        # Metadata and semantics both live in the document as served; `content` has already
        # been processed by this point and no longer contains the head.
        html = getattr(result, "raw_html", "") or getattr(result, "content", "")
        if not html:
            return json.dumps({"error": "Failed to fetch page content", "url": url}, ensure_ascii=False)

        base_url = getattr(result, "final_url", None) or url
        extracted = extract_by_schema(html, parsed, base_url)
        return json.dumps(extracted.to_dict(), ensure_ascii=False, indent=2)

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

            # The service keeps its own per-request accounting; `get_health_report()` reads a
            # different counter set and reports `observed: false` until that one is touched.
            # Measured: after two searches the service had
            # `{'bing': {'error': 2}, 'duckduckgo': {'error': 2}}` and
            # `{'TRY_NEXT_PROVIDER': 4}` while the report showed zero requests.
            #
            # Surfacing it answers the question the report cannot: whether a second backend
            # was ever reached. On CI, 190 searches were all served by bing with no way to
            # distinguish "fallback never needed" from "fallback never fired".
            try:
                outcomes = getattr(search_service, "provider_outcomes", None) or {}
                actions = getattr(search_service, "recovery_actions", None) or {}
                reasons = getattr(search_service, "recovery_reasons", None) or {}
                # Count the counters by name.
                #
                # Summing `stats.values()` treated every entry as a count, so adding
                # `last_failure_kind` made `int('provider')` raise ValueError. The
                # surrounding except swallowed it and this section silently became an error
                # object - but only once a real failure had been recorded, which is why the
                # tests (run before any search) stayed green.
                counters = ("success", "empty", "error")
                total = sum(
                    sum(int(stats.get(k, 0) or 0) for k in counters)
                    for stats in outcomes.values()
                    if isinstance(stats, dict)
                )
                unified_report["provider_activity"] = {
                    "per_provider": {name: dict(stats) for name, stats in outcomes.items()},
                    "recovery_actions": dict(actions),
                    "recovery_reasons": dict(reasons),
                    "outcome_events": total,
                    "providers_contacted": sorted(name for name, stats in outcomes.items() if any(stats.values())),
                    "note": (
                        "Counts from the live search path. An empty map means no search has "
                        "run in this process yet, not that the backends are unused."
                    ),
                }
            except Exception as exc:  # noqa: BLE001 - reporting must not break the report
                unified_report["provider_activity"] = {"error": f"Failed to read activity: {exc}"}

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
        Relative URLs are resolved against the final (post-redirect) URL.
        SSRF safety is enforced on the initial URL and every redirect hop.
        """
        try:
            result = await metadata_fetcher.fetch(url=url, extract=False, output_format="html", max_chars=200000)
            # Metadata lives in <head>, which `content` does not contain once the body has
            # been processed - measured 18979 chars of text against 81061 chars of raw HTML
            # for the same page. Reading `content` first made this tool return empty
            # metadata for every page that had a usable head.
            html = getattr(result, "raw_html", "") or getattr(result, "content", "")
            if not html:
                return json.dumps({"error": "Failed to fetch page content", "url": url}, ensure_ascii=False)
            # Use final_url (post-redirect) as base for resolving relative URLs;
            # fall back to original url if final_url is unavailable.
            base_url = getattr(result, "final_url", None) or url
            metadata = metadata_extractor.extract(html, base_url=base_url)
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
            # `markdown`, not `text`: the plain-text format collapses blank lines, and the
            # analyzer splits paragraphs on them. Measured on a real article - text gave 0
            # double-newlines and a paragraph_count of 1; markdown gave 79 and 80. Word count
            # was identical (4015) in both, so the structural metric was silently wrong next
            # to a correct-looking one. Same for the fetch above.
            result = await fetcher.fetch(url=url, extract=True, output_format="markdown", max_chars=50000)
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
            from .extras.broken_link_checker import BrokenLinkChecker

            checker = BrokenLinkChecker(timeout=timeout)

            # Fetch the starting page with the same SSRF guard and pinned-IP transport
            # used for link checks. This closes the validation-to-connect DNS rebinding gap.
            html, final_url, fetch_error = await checker.fetch_page_html(url, max_chars=200000)
            if fetch_error:
                return json.dumps(
                    {"error": "Failed to fetch page content", "reason": fetch_error, "url": url},
                    ensure_ascii=False,
                )
            if not html:
                return json.dumps({"error": "Failed to fetch page content", "url": url}, ensure_ascii=False)

            # Resolve relative links against the final URL after any safe redirects.
            report = checker.check_page(html, base_url=final_url or url)
            return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("broken_links failed", extra={"url": url, "error": str(exc)})
            return json.dumps({"error": f"Broken link check failed: {exc}", "url": url}, ensure_ascii=False)

    @mcp.tool()
    async def web_knowledge_graph(
        url: str = "",
        text: str = "",
        max_entities: int = 50,
        include_centrality: bool = True,
    ) -> str:
        """Build a knowledge graph of entities and relationships from a page or text.

        Extracts named entities (people, organizations, locations, technologies) and
        the relationships between them, then ranks entities by centrality.

        Provide either `url` (fetched first) or `text` (used directly). This is useful
        for mapping who/what a document is about and how they connect, rather than
        reading it linearly.

        Relationship types are currently `co_occurs_with` only: relationships come
        from proximity, not from parsing sentence semantics. Entity types are
        rule-based, so some are reported as `unknown` rather than guessed.
        """
        if not url and not text:
            return json.dumps(
                {"error": "Provide either 'url' or 'text'"},
                ensure_ascii=False,
            )

        try:
            from .extras.knowledge_graph import KnowledgeGraphBuilder
            from .fetch_provider import FetchRequest

            source = "text"
            source_url = None
            payload = text

            if url:
                # Through fetch_service, like web_fetch: that is where the SSRF guard,
                # provider selection, TLS impersonation fallback, browser escalation and
                # recovery classification live. Calling `fetcher` directly bypassed all
                # of it and returned empty content on pages web_fetch reads fine.
                route = await fetch_service.fetch(
                    FetchRequest(
                        url=url,
                        extract=True,
                        output_format="text",
                        max_chars=200_000,
                    )
                )
                fetched = route.primary_response.content or ""
                if not fetched:
                    return json.dumps(
                        {
                            "error": "Failed to fetch page content",
                            "url": url,
                            # A challenge page is a 200 with a short body. Reporting the
                            # recovery outcome lets the caller tell "blocked" from
                            # "genuinely empty" instead of receiving an empty graph.
                            "recovery_reason": (
                                route.recovery_decision.reason.value if route.recovery_decision is not None else None
                            ),
                            "recovery_outcome": route.recovery_outcome,
                        },
                        ensure_ascii=False,
                    )
                payload = fetched
                source = "url"
                source_url = url

            builder = KnowledgeGraphBuilder()
            graph = builder.build(payload)

            entities = sorted(graph.entities.values(), key=lambda e: e.count, reverse=True)[: max(1, max_entities)]

            entity_rows = [
                {
                    "id": e.id,
                    "name": e.name,
                    "type": e.type,
                    "mentions": e.count,
                }
                for e in entities
            ]

            top_ids = {e.id for e in entities}
            relationships = [
                {
                    "source": r.source,
                    "target": r.target,
                    "type": r.type,
                    "weight": r.weight,
                    "count": r.count,
                }
                for r in graph.relationships
                if r.source in top_ids and r.target in top_ids
            ]

            out: dict = {
                "source": source,
                "entities": entity_rows,
                "relationships": relationships,
                "stats": {
                    "entity_count": len(graph.entities),
                    "relationship_count": len(graph.relationships),
                    "chars_analyzed": len(payload),
                },
                "notes": [
                    "Relationships are co-occurrence based (type: co_occurs_with), not semantic.",
                    "Entity type 'unknown' means the pattern did not identify it; it is not a guess.",
                ],
            }
            if source_url:
                out["url"] = source_url

            if include_centrality:
                try:
                    centrality = builder.calculate_centrality(graph)
                    top = sorted(centrality.items(), key=lambda kv: kv[1], reverse=True)[:10]
                    out["top_entities_by_centrality"] = [{"id": k, "score": round(v, 4)} for k, v in top]
                except Exception:  # pragma: no cover - ranking is best-effort
                    log.debug("centrality failed", exc_info=True)

            return json.dumps(out, ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("web_knowledge_graph failed", extra={"url": url, "error": str(exc)})
            return json.dumps(
                {"error": f"Knowledge graph extraction failed: {exc}", "url": url},
                ensure_ascii=False,
            )

    @mcp.tool()
    async def web_rag_context(
        url: str = "",
        text: str = "",
        query: str = "",
        top_k: int = 5,
        max_chunk_size: int = 60,
    ) -> str:
        """Retrieve the passages of a page most relevant to a query, compressed to fit a context window.

        Splits the content into sentence-aligned passages, ranks them against `query`,
        and returns the best ones together with a compressed context block. Use this
        when a page is too long to hand to a model whole, or when you need to find the
        specific passages that answer a question.

        Provide either `url` (fetched first) or `text` (used directly). `query` is
        required: this tool retrieves, it does not summarise.

        Ranking is lexical (stop-word-filtered IDF over content terms), not embedding
        based, so a query phrased with different vocabulary than the document will miss.
        Use `compressed_context` as the text to pass to a model; `chunks` are for
        inspection and citation.
        """
        if not url and not text:
            return json.dumps(
                {"error": "Provide either 'url' or 'text'"},
                ensure_ascii=False,
            )
        if not query.strip():
            return json.dumps(
                {
                    "error": (
                        "Provide a 'query'. This tool retrieves relevant passages; "
                        "it does not summarise the whole page."
                    )
                },
                ensure_ascii=False,
            )

        try:
            from .extras.rag_optimizer import RAGOptimizer
            from .fetch_provider import FetchRequest

            source = "text"
            source_url = None
            payload = text

            if url:
                # Through fetch_service, exactly as web_fetch does.
                route = await fetch_service.fetch(
                    FetchRequest(
                        url=url,
                        extract=True,
                        output_format="text",
                        max_chars=200_000,
                    )
                )
                fetched = route.primary_response.content or ""
                if not fetched:
                    return json.dumps(
                        {
                            "error": "Failed to fetch page content",
                            "url": url,
                            "recovery_reason": (
                                route.recovery_decision.reason.value if route.recovery_decision is not None else None
                            ),
                            "recovery_outcome": route.recovery_outcome,
                        },
                        ensure_ascii=False,
                    )
                payload = fetched
                source = "url"
                source_url = url

            # A sentence-scale chunk size: at the library default of 500 words a normal
            # article stays one chunk and there is nothing to rank.
            optimizer = RAGOptimizer(max_chunk_size=max(20, int(max_chunk_size)))
            chunks = optimizer.prepare_documents([payload])
            response = optimizer.retrieve(query, chunks, top_k=max(1, int(top_k)))

            passages = [
                {
                    "chunk_id": c.chunk_id,
                    "score": c.score,
                    "words": c.word_count,
                    "text": c.text,
                }
                for c in response.chunks
            ]

            out: dict = {
                "source": source,
                "query": query,
                "rewritten_query": response.rewritten_query or None,
                "passages": passages,
                "compressed_context": response.compressed_context,
                "stats": {
                    "chunks_total": len(chunks),
                    "chunks_returned": len(passages),
                    "chars_analyzed": len(payload),
                    "processing_time_ms": response.processing_time_ms,
                },
                "retrieval_score": round(response.retrieval_score, 4),
                "confidence": round(response.confidence, 4),
                "notes": [
                    (
                        "Ranking is lexical (stop-word-filtered IDF), not embedding-based: "
                        "a query worded differently from the document may miss."
                    ),
                    "compressed_context is the text to hand to a model; passages are for citation.",
                    "Chunks are sentence-aligned, so each passage reads as complete sentences.",
                ],
            }
            if source_url:
                out["url"] = source_url

            return json.dumps(out, ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("web_rag_context failed", extra={"url": url, "error": str(exc)})
            return json.dumps(
                {"error": f"RAG retrieval failed: {exc}", "url": url},
                ensure_ascii=False,
            )

    @mcp.tool()
    async def web_compare_sites(urls: list[str], names: list[str] = None) -> str:
        """Compare several websites side by side on SEO, performance, content and links.

        Fetches each URL, computes metrics, and returns a ranked comparison with a
        per-metric matrix and prioritised recommendations. Use this to benchmark a page
        against competitors, or to check whether your own pages regress.

        Scores are 0-100 per axis and a weighted overall. Comparisons are only as good
        as the markup available to a plain HTTP fetch: a JavaScript-rendered page may
        look thin even when it is not, and that will be visible as a low content score.

        A URL that cannot be fetched is reported as an entry with an `error` and its
        recovery reason, rather than failing the whole comparison.
        """
        if not urls:
            return json.dumps({"error": "Provide at least one URL in 'urls'"}, ensure_ascii=False)
        if len(urls) > 10:
            return json.dumps(
                {"error": "At most 10 URLs per comparison", "count": len(urls)},
                ensure_ascii=False,
            )
        if names is not None and len(names) != len(urls):
            return json.dumps(
                {
                    "error": "'names' must have the same length as 'urls'",
                    "urls": len(urls),
                    "names": len(names),
                },
                ensure_ascii=False,
            )

        try:
            from .extras.competitor_analyzer import compare_sites
            from .extras.content_quality import analyze_content_quality
            from .extras.performance_analyzer import analyze_performance
            from .extras.seo_metrics import extract_seo_metrics
            from .fetch_provider import FetchRequest

            sites: list[dict] = []
            failures: list[dict] = []

            for index, url in enumerate(urls):
                label = names[index] if names else url
                try:
                    # Raw HTML: performance and SEO metrics both need the markup.
                    route = await fetch_service.fetch(
                        FetchRequest(
                            url=url,
                            extract=False,
                            output_format="html",
                            max_chars=2_000_000,
                        )
                    )
                    html = route.primary_response.content or ""
                    if not html:
                        failures.append(
                            {
                                "url": url,
                                "name": label,
                                "error": "Failed to fetch page content",
                                "recovery_reason": (
                                    route.recovery_decision.reason.value
                                    if route.recovery_decision is not None
                                    else None
                                ),
                                "recovery_outcome": route.recovery_outcome,
                            }
                        )
                        continue

                    # The end tag may carry whitespace (`</script >` is valid HTML). A bare
                    # `</script>` pattern misses it, letting script text survive into the text
                    # metrics and inflate the content score. CodeQL flagged this before release.
                    # Strip tags for the text-based analyzers; keep markup for the rest.
                    plain = re.sub(r"<script[^>]*>.*?</script[^>]*>", " ", html, flags=re.DOTALL | re.IGNORECASE)
                    plain = re.sub(r"<style[^>]*>.*?</style[^>]*>", " ", plain, flags=re.DOTALL | re.IGNORECASE)
                    plain = re.sub(r"<[^>]+>", " ", plain)

                    perf = analyze_performance(html, url=url)
                    quality = analyze_content_quality(plain, html=html)

                    sites.append(
                        {
                            "url": url,
                            "name": label,
                            "seo": extract_seo_metrics(html, url),
                            "performance": (perf.to_dict() if hasattr(perf, "to_dict") else vars(perf)),
                            "content": (quality.to_dict() if hasattr(quality, "to_dict") else vars(quality)),
                            "links": {},
                            "status_code": route.primary_response.status_code,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - one bad site must not sink the rest
                    log.warning("compare_sites: fetch failed", extra={"url": url, "error": str(exc)})
                    failures.append({"url": url, "name": label, "error": str(exc)})

            if not sites:
                return json.dumps(
                    {
                        "error": "No site could be fetched",
                        "failures": failures,
                    },
                    ensure_ascii=False,
                )

            result = compare_sites(
                [
                    {
                        "url": s["url"],
                        "name": s["name"],
                        "seo": s["seo"],
                        "performance": s["performance"],
                        "content": s["content"],
                        "links": s["links"],
                    }
                    for s in sites
                ]
            )
            payload = result.to_dict() if hasattr(result, "to_dict") else vars(result)
            payload["failures"] = failures
            payload["notes"] = [
                "Scores are heuristic (0-100 per axis, weighted overall), not a search-engine ranking.",
                "Metrics come from a plain HTTP fetch: a JS-rendered page can look thin when it is not.",
                "Images with an empty alt attribute do not count toward accessibility.",
            ]
            return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("web_compare_sites failed", extra={"urls": urls, "error": str(exc)})
            return json.dumps(
                {"error": f"Site comparison failed: {exc}", "urls": urls},
                ensure_ascii=False,
            )

    @mcp.tool()
    async def web_monitor(
        url: str,
        ignore_text: list[str] = None,
        ignore_selector: list[str] = None,
        price_selector: str = "",
        price_change_threshold: float = 0.0,
        min_change_size: int = 10,
        keywords_appear: list[str] = None,
        include_diff: bool = True,
        state_path: str = "",
        notify: list[str] = None,
        json_path: str = "",
    ) -> str:
        """Check a URL for changes since the last check, and return what changed.

        Compares the page against the last snapshot stored on disk and reports text
        changes, price moves, and keyword appearances or disappearances. Useful for
        tracking a page across sessions: docs, prices, availability, job postings.

        **This checks once per call.** It does not schedule itself - an MCP tool is
        passive. To monitor continuously, call it again from your MCP client or an
        external scheduler. The first call for a URL only records a baseline and returns
        no changes.

        Use `ignore_text` (regexes) for values that change on every request such as
        timestamps or session ids, and `ignore_selector` (CSS) for regions that churn
        independently such as ad slots. Without them most pages report a change every
        time, which is why they exist.

        Price watching is independent of `min_change_size`: a one-character move like
        $100.00 to $900.00 is exactly what a text threshold would swallow, so it is
        compared as a percentage when `price_selector` is set.

        `json_path` watches one value inside a JSON response instead of the whole body:
        `json:$.product.price` uses JSONPath, `jq:.product.price` uses jq (needs the
        `[json]` extra; JSONPath needs it too). Reducing an API response to one field is
        what makes it stable enough to monitor - markup and prose churn, a price field
        does not. Without `json_path` the whole body is compared as before.

        `notify` takes target URLs such as `webhook://example.com/hook`,
        `dingtalk://oapi.dingtalk.com/robot/send?access_token=X`, `telegram://TOKEN@CHAT`
        or `smtp://user:pass@host:587?to=a@b.c`. When a change is found it is pushed to
        those channels, and the send result is reported in `notifications`. Credentials
        stay in the URL and are never echoed back.
        """
        if not url or not url.strip():
            return json.dumps({"error": "Provide a 'url' to check"}, ensure_ascii=False)

        try:
            from .extras.monitor import MonitorConfig, WebMonitor
            from .fetch_provider import FetchRequest

            config_kwargs: dict = {
                "monitor_text": True,
                "monitor_html": False,
                "min_change_size": max(0, int(min_change_size)),
                "include_diff": bool(include_diff),
            }
            if ignore_text:
                config_kwargs["ignore_text"] = list(ignore_text)
            if ignore_selector:
                config_kwargs["ignore_selector"] = list(ignore_selector)
            if price_selector:
                config_kwargs["price_selector"] = price_selector
                config_kwargs["price_change_threshold"] = max(0.0, float(price_change_threshold))
            if keywords_appear:
                config_kwargs["keywords_appear"] = list(keywords_appear)
            if state_path:
                config_kwargs["history_path"] = state_path

            # Set only on the JSON path; initialised here so the response block below can
            # ask whether a selector was used without a NameError on the other branch.
            payload_selected = None

            # JSON selection: fetch once, reduce the body to the selected value, and hand
            # the monitor that text instead of the raw response. Doing it here rather
            # than inside the monitor keeps extraction and comparison separate, which is
            # how changedetection.io structures the same problem.
            if json_path:
                from .json_select import SelectError, available_languages, extract

                langs = available_languages()
                if not langs["jsonpath"] and not langs["jq"]:
                    return json.dumps(
                        {
                            "error": (
                                "json_path needs the [json] extra. Install it with: pip install 'webscout-mcp[json]'"
                            ),
                            "url": url,
                        },
                        ensure_ascii=False,
                    )

                probe = await fetch_service.fetch(
                    FetchRequest(
                        url=url,
                        extract=False,
                        output_format="text",
                        max_chars=2_000_000,
                        # A monitor that reads a cached body reports "no change" forever.
                        # Measured: the server returned 900 while the cache still yielded
                        # 100, so the comparison saw the old value every time.
                        bypass_cache=True,
                    )
                )
                body = probe.primary_response.content or ""
                if not body:
                    return json.dumps(
                        {
                            "error": "Failed to fetch page content",
                            "url": url,
                            "recovery_reason": (
                                probe.recovery_decision.reason.value if probe.recovery_decision is not None else None
                            ),
                            "recovery_outcome": probe.recovery_outcome,
                        },
                        ensure_ascii=False,
                    )
                try:
                    selected = extract(body, json_path)
                except SelectError as exc:
                    return json.dumps(
                        {
                            "error": str(exc),
                            "url": url,
                            "selector": json_path,
                            "available_languages": langs,
                        },
                        ensure_ascii=False,
                    )

                class _SelectedFetcher:
                    """Serve the already-selected value; the monitor never hits the network."""

                    def fetch(self, _url, **_kwargs):
                        from .monitor_adapter import MonitorFetchResult

                        return MonitorFetchResult(content=selected, html=selected)

                config = MonitorConfig(**config_kwargs)
                monitor = WebMonitor(config=config, fetcher=_SelectedFetcher())
            else:
                # Route through fetch_service so monitoring inherits TLS impersonation,
                # browser escalation and recovery classification. Without this the
                # monitor does its own HTTP and a page needing either of those returns
                # "no change" forever, because the fetch itself never succeeds.
                from .monitor_adapter import FetchServiceAdapter

                config = MonitorConfig(**config_kwargs)
                monitor = WebMonitor(config=config, fetcher=FetchServiceAdapter(fetch_service))

            # Notification targets resolved from URLs: the eight channels each need their
            # own constructor, so a URL is the only shape a caller can assemble reliably.
            notification_targets: list[str] = list(notify or [])
            notification_errors: list[dict] = []
            if notification_targets:
                from .extras.alert_targets import build_channel

                for target in notification_targets:
                    try:
                        monitor.add_alert_channel(build_channel(target))
                    except Exception as exc:  # noqa: BLE001 - one bad target must not block
                        notification_errors.append(
                            {
                                "target": target.split("://")[0] + "://...",
                                "error": str(exc),
                            }
                        )

            # Known before the check, to report whether this run was a baseline.
            known_before = bool(monitor._last_content.get(url))

            # check_url is synchronous and performs HTTP itself; running it inline would
            # block the event loop for a full network round trip.
            changes = await asyncio.to_thread(monitor.check_url, url)

            out = {
                "url": url,
                "changes": [c.to_dict() for c in changes],
                "change_count": len(changes),
                "baseline_established": (not known_before) and not changes,
                "state_path": config.history_path,
                "notifications": {
                    "targets": [t.split("://")[0] + "://..." for t in notification_targets],
                    "errors": notification_errors,
                    # Per-send outcome. Without this a failed channel is indistinguishable
                    # from a delivered one, which is how the notification path stayed
                    # broken while looking wired up.
                    "delivery": getattr(monitor, "last_delivery", []) or [],
                },
                "notes": [
                    "This tool checks once per call; scheduling is the caller's job.",
                    (
                        "Routes through fetch_service: inherits TLS impersonation, browser "
                        "escalation and recovery classification."
                    ),
                    "Reported changes are stored, so a repeat call sees only new ones.",
                ],
            }
            if payload_selected is not None:
                # Echo what was actually watched. Without it a caller cannot tell whether
                # the selector matched the field they meant, and a wrong path looks the
                # same as a page that never changes.
                out["json_path"] = json_path
                out["selected_value"] = payload_selected

            if not changes and not out["baseline_established"]:
                out["notes"].append(
                    "No change since the last check. If you expected one, widen "
                    "min_change_size or check ignore_text/ignore_selector are not too broad."
                )
            return json.dumps(out, ensure_ascii=False, indent=2, default=str)
        except Exception as exc:
            log.error("web_monitor failed", extra={"url": url, "error": str(exc)})
            return json.dumps(
                {"error": f"Monitor check failed: {exc}", "url": url},
                ensure_ascii=False,
            )

    return mcp
