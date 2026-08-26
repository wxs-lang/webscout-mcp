"""Command-line entry point for webscout-mcp.

Usage:
    webscout-mcp                  # Start MCP server over stdio (default)
    webscout-mcp --transport sse  # Start MCP server over SSE
    webscout-mcp --version        # Print version
    webscout-mcp --help           # Show help
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .config import Config


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="webscout-mcp",
        description="A smart web search & fetch MCP server with caching and content extraction.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"webscout-mcp {__version__}",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="MCP transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for SSE transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE transport (default: 8000)",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Override cache directory",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=None,
        help="Override cache TTL in seconds",
    )

    args = parser.parse_args()

    # Build config
    config = Config.from_env()
    if args.cache_dir:
        from pathlib import Path
        config.cache_dir = Path(args.cache_dir)
    if args.cache_ttl is not None:
        config.cache_ttl = args.cache_ttl

    # Create and run server
    from .server import create_server
    mcp = create_server(config)

    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
