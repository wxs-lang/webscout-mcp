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

    return parser


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
