"""Command-line interface for webscout-mcp.

Subcommands:
    webscout-mcp serve [--transport stdio|sse]   Start MCP server (default)
    webscout-mcp search <query> [--max-results N]  Search the web
    webscout-mcp fetch <url> [--extract] [--format markdown|text|html]  Fetch a page
    webscout-mcp crawl <url> [--depth N] [--pages N]  Crawl a site
    webscout-mcp sitemap <url> [--discover]  Parse/discover sitemaps
    webscout-mcp export <type> [--query/--url] [--format json|csv|markdown]  Export results
    webscout-mcp --version                          Print version
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import Config
from .logging_config import get_logger, setup_logging


def _build_config(args: argparse.Namespace) -> Config:
    config = Config.from_env()
    if getattr(args, "cache_dir", None):
        config.cache_dir = Path(args.cache_dir)
    if getattr(args, "cache_ttl", None) is not None:
        config.cache_ttl = args.cache_ttl
    if getattr(args, "verbose", False):
        import os

        os.environ.setdefault("WEBSCOUT_LOG_LEVEL", "DEBUG")
    return config


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


async def _cmd_serve(args: argparse.Namespace) -> None:
    from .server import create_server

    config = _build_config(args)
    config.ensure_dirs()
    mcp = create_server(config)
    log = get_logger("cli")
    log.info(f"starting MCP server, transport={args.transport}")
    if mcp is None:
        log.error("Failed to create MCP server")
        sys.exit(1)
    if args.transport == "sse":
        await mcp.run_sse_async(host=args.host, port=args.port)
    else:
        # Use async run_stdio_async() instead of synchronous run()
        # because run() internally calls anyio.run(), which would fail
        # with "Already running asyncio in this thread" since we're
        # already inside an asyncio.run() event loop.
        await mcp.run_stdio_async()


async def _cmd_search(args: argparse.Namespace) -> None:
    from .cache import Cache
    from .search import SearchEngine

    config = _build_config(args)
    config.ensure_dirs()
    cache = Cache(db_path=config.cache_dir / "webscout.db", ttl=config.cache_ttl, max_size_mb=config.cache_max_size_mb)
    engine = SearchEngine(config, cache)
    try:
        results = await engine.search(query=args.query, max_results=args.max_results, safe_search=not args.unsafe)
        output = [
            {"position": r.position, "title": r.title, "url": r.url, "snippet": r.snippet, "backend": r.backend}
            for r in results
        ]
        _print_json({"query": args.query, "count": len(output), "results": output})
    finally:
        await engine.close()


async def _cmd_fetch(args: argparse.Namespace) -> None:
    from .cache import Cache
    from .fetcher import Fetcher

    config = _build_config(args)
    config.ensure_dirs()
    cache = Cache(db_path=config.cache_dir / "webscout.db", ttl=config.cache_ttl, max_size_mb=config.cache_max_size_mb)
    fetcher = Fetcher(config, cache)
    try:
        result = await fetcher.fetch(
            url=args.url,
            extract=args.extract,
            output_format=args.format,
            max_chars=args.max_chars,
            bypass_cache=args.no_cache,
        )
        if args.raw:
            print(result.content)
        else:
            _print_json(result.to_dict())
    finally:
        await fetcher.close()


async def _cmd_crawl(args: argparse.Namespace) -> None:
    from .cache import Cache
    from .crawler import Crawler
    from .fetcher import Fetcher
    from .robots import RobotsChecker

    config = _build_config(args)
    config.ensure_dirs()
    cache = Cache(db_path=config.cache_dir / "webscout.db", ttl=config.cache_ttl, max_size_mb=config.cache_max_size_mb)
    fetcher = Fetcher(config, cache)
    robots = RobotsChecker(config, respect_robots=config.respect_robots)
    crawler = Crawler(config, fetcher, robots)
    try:
        result = await crawler.crawl(
            seed_url=args.url,
            max_depth=args.depth,
            max_pages=args.pages,
            same_domain_only=not args.allow_external,
            extract=not args.no_extract,
        )
        _print_json(result.to_dict())
    finally:
        await fetcher.close()
        await robots.close()


async def _cmd_sitemap(args: argparse.Namespace) -> None:
    from .sitemap import SitemapParser

    config = _build_config(args)
    parser = SitemapParser(config)
    try:
        if args.discover:
            sitemaps = await parser.discover_sitemaps(args.url)
            if not sitemaps:
                _print_json({"url": args.url, "sitemaps": [], "error": "No sitemaps found"})
                return
            all_urls = []
            all_errors = []
            for sm_url in sitemaps:
                result = await parser.fetch_sitemap(sm_url, recursive=not args.no_recursive)
                all_urls.extend(result.urls)
                all_errors.extend(result.errors)
            _print_json(
                {
                    "seed": args.url,
                    "sitemaps_discovered": sitemaps,
                    "url_count": len(all_urls),
                    "urls": [{"url": u.url, "lastmod": u.lastmod.isoformat() if u.lastmod else None} for u in all_urls],
                    "errors": all_errors,
                }
            )
        else:
            result = await parser.fetch_sitemap(args.url, recursive=not args.no_recursive)
            _print_json(
                {
                    "source": result.source_url,
                    "is_index": result.is_index,
                    "url_count": result.url_count,
                    "sub_sitemaps": result.sub_sitemaps,
                    "urls": [
                        {"url": u.url, "lastmod": u.lastmod.isoformat() if u.lastmod else None} for u in result.urls
                    ],
                    "errors": result.errors,
                }
            )
    finally:
        await parser.close()


async def _cmd_export(args: argparse.Namespace) -> None:
    from .exporter import Exporter

    if args.type == "search":
        from .cache import Cache
        from .search import SearchEngine

        config = _build_config(args)
        config.ensure_dirs()
        cache = Cache(
            db_path=config.cache_dir / "webscout.db", ttl=config.cache_ttl, max_size_mb=config.cache_max_size_mb
        )
        engine = SearchEngine(config, cache)
        try:
            results = await engine.search(query=args.query, max_results=args.max_results)
            if args.format == "json":
                content = Exporter.search_to_json(results)
            elif args.format == "csv":
                content = Exporter.search_to_csv(results)
            else:
                content = Exporter.search_to_markdown(results, title=f"Search: {args.query}")
            if args.output:
                Exporter.save(content, args.output)
                print(f"Exported to {args.output}")
            else:
                print(content)
        finally:
            await engine.close()
    elif args.type == "fetch":
        from .cache import Cache
        from .fetcher import Fetcher

        config = _build_config(args)
        config.ensure_dirs()
        cache = Cache(
            db_path=config.cache_dir / "webscout.db", ttl=config.cache_ttl, max_size_mb=config.cache_max_size_mb
        )
        fetcher = Fetcher(config, cache)
        try:
            result = await fetcher.fetch(url=args.url, extract=True, output_format="markdown")
            if args.format == "json":
                content = Exporter.fetch_to_json(result)
            else:
                content = Exporter.fetch_to_markdown(result)
            if args.output:
                Exporter.save(content, args.output)
                print(f"Exported to {args.output}")
            else:
                print(content)
        finally:
            await fetcher.close()


async def _cmd_cache(args: argparse.Namespace) -> None:
    """Cache management commands."""
    from .cache import Cache

    config = _build_config(args)
    config.ensure_dirs()
    cache = Cache(db_path=config.cache_dir / "webscout.db", ttl=config.cache_ttl, max_size_mb=config.cache_max_size_mb)

    if args.cache_command == "stats":
        stats = cache.stats()
        _print_json(
            {
                "cache_dir": str(config.cache_dir),
                "db_path": str(config.cache_dir / "webscout.db"),
                "ttl_seconds": config.cache_ttl,
                "max_size_mb": config.cache_max_size_mb,
                "stats": stats,
            }
        )
    elif args.cache_command == "clear":
        cache.clear()
        print("Cache cleared successfully.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webscout-mcp", description="A smart web search & fetch MCP server with caching and content extraction."
    )
    parser.add_argument("--version", action="version", version=f"webscout-mcp {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose (DEBUG) logging")
    parser.add_argument("--cache-dir", default=None, help="Override cache directory")
    parser.add_argument("--cache-ttl", type=int, default=None, help="Override cache TTL in seconds")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    serve_parser = subparsers.add_parser("serve", help="Start the MCP server (default if no command given)")
    serve_parser.add_argument(
        "--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport protocol (default: stdio)"
    )
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host for SSE transport")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port for SSE transport")
    serve_parser.set_defaults(func=_cmd_serve)

    search_parser = subparsers.add_parser("search", help="Search the web and print results as JSON")
    search_parser.add_argument("query", help="Search query string")
    search_parser.add_argument("--max-results", type=int, default=10, help="Maximum number of results")
    search_parser.add_argument("--unsafe", action="store_true", help="Disable safe search")
    search_parser.set_defaults(func=_cmd_search)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch a URL and print its content")
    fetch_parser.add_argument("url", help="URL to fetch")
    fetch_parser.add_argument(
        "--no-extract", dest="extract", action="store_false", help="Don't extract main article content"
    )
    fetch_parser.add_argument(
        "--format", choices=["markdown", "text", "html"], default="markdown", help="Output format when extracting"
    )
    fetch_parser.add_argument("--max-chars", type=int, default=8000, help="Maximum characters to return")
    fetch_parser.add_argument("--no-cache", action="store_true", help="Bypass cache and re-fetch")
    fetch_parser.add_argument("--raw", action="store_true", help="Print only the content (no JSON wrapper)")
    fetch_parser.set_defaults(func=_cmd_fetch)

    crawl_parser = subparsers.add_parser("crawl", help="Crawl a website and print results as JSON")
    crawl_parser.add_argument("url", help="Seed URL to start crawling from")
    crawl_parser.add_argument("--depth", type=int, default=2, help="Maximum link depth")
    crawl_parser.add_argument("--pages", type=int, default=10, help="Maximum number of pages to crawl")
    crawl_parser.add_argument("--allow-external", action="store_true", help="Allow crawling pages on different domains")
    crawl_parser.add_argument("--no-extract", action="store_true", help="Don't extract main content from crawled pages")
    crawl_parser.set_defaults(func=_cmd_crawl)

    sitemap_parser = subparsers.add_parser("sitemap", help="Fetch and parse a sitemap.xml")
    sitemap_parser.add_argument("url", help="Sitemap URL or domain to discover sitemaps")
    sitemap_parser.add_argument("--discover", action="store_true", help="Discover sitemaps for the given domain")
    sitemap_parser.add_argument("--no-recursive", action="store_true", help="Don't recursively fetch sub-sitemaps")
    sitemap_parser.set_defaults(func=_cmd_sitemap)

    export_parser = subparsers.add_parser("export", help="Export search/fetch results to JSON/CSV/Markdown")
    export_parser.add_argument("type", choices=["search", "fetch"], help="Type of content to export")
    export_parser.add_argument("--query", help="Search query (for type=search)")
    export_parser.add_argument("--url", help="URL to fetch (for type=fetch)")
    export_parser.add_argument("--max-results", type=int, default=10, help="Max search results")
    export_parser.add_argument("--format", choices=["json", "csv", "markdown"], default="json", help="Output format")
    export_parser.add_argument("--output", "-o", default=None, help="Output file path")
    export_parser.set_defaults(func=_cmd_export)

    cache_parser = subparsers.add_parser("cache", help="Manage the local cache")
    cache_subparsers = cache_parser.add_subparsers(dest="cache_command", help="Cache commands")
    cache_stats_parser = cache_subparsers.add_parser("stats", help="Show cache statistics")
    cache_stats_parser.set_defaults(func=_cmd_cache)
    cache_clear_parser = cache_subparsers.add_parser("clear", help="Clear the cache")
    cache_clear_parser.set_defaults(func=_cmd_cache)

    jev_parser = subparsers.add_parser("jev-report", help="Read-only report of Jev shadow decisions")
    jev_group = jev_parser.add_mutually_exclusive_group(required=False)
    jev_group.add_argument("--last", type=int, metavar="N", help="Show N most recent shadow decisions")
    jev_group.add_argument("--summary", action="store_true", help="Show aggregate summary")
    jev_group.add_argument("--disagreements", type=int, metavar="N", help="Show N rule/Jev disagreements")
    jev_group.add_argument("--errors", action="store_true", help="Show Jev API errors/timeouts")
    jev_parser.add_argument("--provider", default=None, help="Filter by jev_provider (e.g. typesafe/fake)")
    jev_parser.add_argument("--schema-version", default=None, help="Filter by decision_schema_version (e.g. 1)")
    jev_parser.add_argument("--all", action="store_true", help="Include all providers/schema versions")
    jev_parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run a live TypeSafe smoke test (requires TYPESAFE_API_KEY; does not write to DB)",
    )
    jev_parser.set_defaults(func=_cmd_jev_report)

    return parser


async def _cmd_jev_report(args: argparse.Namespace) -> None:
    """Read-only human-readable Jev shadow report."""
    from datetime import datetime

    from .jev_store import (
        configure,
        load_disagreements,
        load_errors,
        load_recent,
        load_summary,
    )

    # Live smoke first — does not touch DB.
    if getattr(args, "smoke", False):
        await _jev_smoke()
        return

    db = configure()
    print(f"Jev shadow DB: {db}")
    provider = getattr(args, "provider", None)
    schema_ver = getattr(args, "schema_version", None)
    show_all = getattr(args, "all", False)
    # Default: only typesafe + current schema. Explicit --all shows everything.
    if not show_all and provider is None and schema_ver is None:
        provider = "typesafe"
        schema_ver = "1"
    if provider:
        print(f"Provider filter: {provider}")
    if schema_ver:
        print(f"Schema filter:   {schema_ver}")

    if args.summary:
        s = load_summary(provider=provider, schema_version=schema_ver)
        print()
        print("=== Jev Shadow Summary ===")
        print(f"provider:          {provider or 'all'}")
        print(f"schema:            {schema_ver or 'all'}")
        print(f"valid decisions:   {s['valid_decisions']}")
        print(f"invalid decisions: {s['invalid_decisions']}")
        print(f"confidence available: {s['confidence_available']}")
        print(f"confidence missing:   {s['confidence_missing']}")
        print(f"usage available:   {s['usage_available']}")
        print(f"usage missing:     {s['usage_missing']}")
        dist = s.get("provider_distribution") or {}
        if dist:
            print("providers seen:")
            for p, n in sorted(dist.items()):
                print(f"  {p}: {n}")
        sv = s.get("schema_versions") or {}
        if sv:
            print("schema versions:")
            for k, n in sorted(sv.items()):
                print(f"  {k}: {n}")
        if s["calls"] == 0:
            print("\nNo matching records yet.")
            return
        print(f"\ncalls:   {s['calls']}")
        print(f"success: {s['success']}")
        print(f"failure: {s['failure']}")
        if s.get("input_tokens") is not None:
            print(f"tokens in/out: {s['input_tokens']} / {s['output_tokens']}")
        if s["latency_p50_ms"] is not None:
            print(f"latency p50:  {s['latency_p50_ms']} ms")
            print(f"latency p95:  {s['latency_p95_ms']} ms")
        q = s["quadrants"]
        print()
        print("rule vs Jev (needs_escalation):")
        print(f"  rule_no  / jev_no : {q['rule_no/jev_no']}")
        print(f"  rule_no  / jev_yes: {q['rule_no/jev_yes']}")
        print(f"  rule_yes / jev_no : {q['rule_yes/jev_no']}")
        print(f"  rule_yes / jev_yes: {q['rule_yes/jev_yes']}")
        if s["agreement_rate"] is not None:
            print(f"agreement rate: {s['agreement_rate']}  (n={s['judged_pairs']})")
        return

    if args.last:
        rows = load_recent(args.last, provider=provider, schema_version=schema_ver)
        print(f"\n=== Last {len(rows)} records ===")
        for r in rows:
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            jev = "Y" if r.get("jev_decision") else "N"
            err = r.get("jev_error") or ""
            print(
                f"{ts}  op={r['operation']:<6} q={r['jev_question']:<18} "
                f"prov={r.get('jev_provider') or '?':<8} v={r.get('schema_version') or '-':<3} "
                f"jev={jev:<1} p={r.get('jev_probability')} "
                f"rule={r.get('rule_decision')} {err}"
            )
        return

    if args.disagreements:
        rows = load_disagreements(args.disagreements, provider=provider, schema_version=schema_ver)
        print(f"\n=== {len(rows)} disagreements (rule != Jev) ===")
        for r in rows:
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"{ts}  q={r['jev_question']:<18} rule={r.get('rule_decision')} "
                f"jev={r.get('jev_decision')} reason={r.get('rule_reason')} "
                f"backend={r.get('backend')}"
            )
        return

    if args.errors:
        rows = load_errors(100, provider=provider, schema_version=schema_ver)
        print(f"\n=== {len(rows)} Jev errors/timeouts ===")
        for r in rows:
            ts = datetime.fromtimestamp(r["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts}  q={r['jev_question']:<18} error={r.get('jev_error')}")
        return


async def _jev_smoke() -> None:
    """Run a live TypeSafe Jev smoke test. Requires TYPESAFE_API_KEY.

    Does NOT write to the shadow database.
    """
    import os

    api_key = os.environ.get("TYPESAFE_API_KEY", "")
    if not api_key:
        print("Live Jev smoke skipped: TYPESAFE_API_KEY not configured")
        return
    from .jev_client import TypeSafeJevClient

    client = TypeSafeJevClient(api_key=api_key, model="jev-latest", timeout_ms=5000)
    print("Running live TypeSafe Jev smoke...")
    try:
        # needs_escalation + result_usable on a synthetic state.
        fetch_state = {
            "title": "Example Domain",
            "content_excerpt": "Example domain. This domain is for use in illustrative examples in documents.",
            "content_length": 90,
            "content_type": "text/html",
            "http_status": 200,
            "extracted": True,
            "empty_content": False,
            "truncated": False,
            "backend": "fast-http",
            "host": "example.com",
        }
        answers = await client.ask_many(["needs_escalation", "result_usable"], fetch_state)
        for q, d in answers.items():
            print(f"  {q}: decision={d.decision} p={d.probability_yes} latency={d.latency_ms:.0f}ms err={d.error}")
        # result_relevant
        search_state = {
            "query": "python asyncio docs",
            "title": "asyncio — Asynchronous I/O",
            "snippet": "Source code for asyncio.",
            "source": "Bing",
            "host": "docs.python.org",
        }
        r = await client.ask("result_relevant", search_state)
        print(
            f"  result_relevant: decision={r.decision} p={r.probability_yes} latency={r.latency_ms:.0f}ms err={r.error}"
        )
        print("Smoke OK (not written to DB).")
    except Exception as exc:  # pragma: no cover
        print(f"Smoke FAILED: {type(exc).__name__}: {exc}")
    finally:
        await client.aclose()


def main() -> None:
    setup_logging()
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        args.command = "serve"
        args.transport = "stdio"
        args.host = "127.0.0.1"
        args.port = 8000
        args.func = _cmd_serve
    try:
        asyncio.run(args.func(args))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:
        log = get_logger("cli")
        log.error(f"command failed: {args.command}, error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
