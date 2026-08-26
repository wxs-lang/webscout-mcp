"""CLI entry point for webscout-mcp.

Provides subcommands for serving the MCP server and direct command-line
usage of search, fetch, and crawl functionality.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from . import __version__
from .config import Config
from .logging import setup_logging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="webscout-mcp",
        description="Web search & fetch MCP server",
    )
    parser.add_argument("--version", action="version", version=f"webscout-mcp {__version__}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start the MCP server (default)")
    serve_parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="Transport protocol")

    # search
    search_parser = subparsers.add_parser("search", help="Search the web")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-n", "--max-results", type=int, default=10, help="Max results (1-25)")
    search_parser.add_argument("--region", default="wt-wt", help="Search region")
    search_parser.add_argument("--no-safe", action="store_true", help="Disable safe search")

    # fetch
    fetch_parser = subparsers.add_parser("fetch", help="Fetch a URL")
    fetch_parser.add_argument("url", help="URL to fetch")
    fetch_parser.add_argument("--no-extract", action="store_true", help="Skip main content extraction")
    fetch_parser.add_argument("--format", choices=["markdown", "text", "html"], default="markdown", help="Output format")
    fetch_parser.add_argument("--max-chars", type=int, default=8000, help="Max characters")
    fetch_parser.add_argument("--bypass-cache", action="store_true", help="Skip cache")

    # crawl
    crawl_parser = subparsers.add_parser("crawl", help="Crawl a website")
    crawl_parser.add_argument("url", help="Seed URL")
    crawl_parser.add_argument("--depth", type=int, default=2, help="Max depth (0-5)")
    crawl_parser.add_argument("--pages", type=int, default=10, help="Max pages (1-50)")
    crawl_parser.add_argument("--no-same-domain", action="store_true", help="Allow cross-domain")
    crawl_parser.add_argument("--no-extract", action="store_true", help="Skip content extraction")
    crawl_parser.add_argument("--concurrency", type=int, default=5, help="Concurrent fetches (1-20)")

    return parser


async def _cmd_search(args: argparse.Namespace) -> int:
    from .cache import Cache
    from .search import SearchEngine
    config = Config.from_env()
    config.ensure_dirs()
    cache = Cache(db_path=config.cache_dir / "webscout.db", ttl=config.cache_ttl, max_size_mb=config.cache_max_size_mb)
    engine = SearchEngine(config, cache)
    try:
        results = await engine.search(
            query=args.query,
            max_results=args.max_results,
            region=args.region,
            safe_search=not args.no_safe,
        )
        output = [
            {"position": r.position, "title": r.title, "url": r.url, "snippet": r.snippet, "backend": r.backend}
            for r in results
        ]
        print(json.dumps({"query": args.query, "count": len(output), "results": output}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "query": args.query}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        await engine.close()


async def _cmd_fetch(args: argparse.Namespace) -> int:
    from .cache import Cache
    from .fetcher import Fetcher
    config = Config.from_env()
    config.ensure_dirs()
    cache = Cache(db_path=config.cache_dir / "webscout.db", ttl=config.cache_ttl, max_size_mb=config.cache_max_size_mb)
    fetcher = Fetcher(config, cache)
    try:
        result = await fetcher.fetch(
            url=args.url,
            extract=not args.no_extract,
            output_format=args.format,
            max_chars=args.max_chars,
            bypass_cache=args.bypass_cache,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if not result.error else 1
    except Exception as exc:
        print(json.dumps({"error": str(exc), "url": args.url}, ensure_ascii=False), file=sys.stderr)
        return 1


async def _cmd_crawl(args: argparse.Namespace) -> int:
    from .cache import Cache
    from .crawler import Crawler
    from .fetcher import Fetcher
    from .robots import RobotsChecker
    config = Config.from_env()
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
            same_domain_only=not args.no_same_domain,
            extract=not args.no_extract,
            concurrency=args.concurrency,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc), "url": args.url}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        await robots.close()


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import create_server
    mcp = create_server()
    if args.transport == "sse":
        print("SSE transport is not yet supported in this version.", file=sys.stderr)
        return 1
    mcp.run(transport="stdio")
    return 0


def main() -> None:
    setup_logging()
    parser = _build_parser()
    args = parser.parse_args()
    if args.command is None or args.command == "serve":
        sys.exit(_cmd_serve(args if args.command == "serve" else argparse.Namespace(transport="stdio")))
    elif args.command == "search":
        sys.exit(asyncio.run(_cmd_search(args)))
    elif args.command == "fetch":
        sys.exit(asyncio.run(_cmd_fetch(args)))
    elif args.command == "crawl":
        sys.exit(asyncio.run(_cmd_crawl(args)))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
