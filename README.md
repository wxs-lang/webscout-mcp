# webscout-mcp

Web search and fetch tools for AI agents, as an MCP server. Search, fetch, crawl, and extract structured data from the web - no API keys, no per-request billing, everything stays on your machine.

## Install

```bash
pip install webscout-mcp
```

Requires Python 3.10+.

## Quick start

Add to your MCP client config (Claude Code, Cursor, Codex, etc.):

```json
{
  "mcpServers": {
    "webscout": {
      "command": "webscout-mcp",
      "args": []
    }
  }
}
```

That's it. Your agent gets six tools:

- `web_search` - search via Bing with automatic DuckDuckGo HTML fallback, no key needed
- `web_fetch` - fetch a page and extract the main article (markdown/text/html)
- `web_crawl` - concurrent BFS crawl with depth/page limits, respects robots.txt
- `web_extract` - pull structured data with CSS selectors, attributes, regex
- `cache_stats` - inspect the local cache
- `cache_clear` - wipe the cache

## CLI usage

```bash
# Search the web (outputs JSON)
webscout-mcp search "python async libraries" --max-results 5

# Fetch a page
webscout-mcp fetch https://example.com --extract --format markdown --raw

# Crawl a site
webscout-mcp crawl https://example.com --depth 2 --pages 10

# Parse a sitemap
webscout-mcp sitemap https://example.com/sitemap.xml

# Discover sitemaps for a domain
webscout-mcp sitemap https://example.com --discover

# Export search results to CSV
webscout-mcp export search --query "python" --format csv --output results.csv

# Start MCP server (default if no command given)
webscout-mcp serve --transport stdio
```

## Usage examples

### Search

```json
web_search(query="best python async libraries", max_results=5)
```

Returns structured results with title, URL, snippet, and which backend served the request (`bing` or `duckduckgo`). If Bing fails or changes its markup, the engine automatically falls back to DuckDuckGo's HTML version.

### Fetch a page

```json
web_fetch(url="https://example.com", extract=true, output_format="markdown")
```

`extract=true` runs trafilatura (with readability-lxml fallback) to strip nav, ads, and sidebars.

### Crawl a site

```json
web_crawl(seed_url="https://example.com", max_depth=2, max_pages=10, concurrency=5)
```

Pages at each depth level are fetched concurrently. The crawler respects `robots.txt` by default.

## Use as a Python library

```python
import asyncio
from webscout_mcp import Config, Fetcher, SearchEngine, Exporter, SitemapParser

async def main():
    config = Config.from_env()
    config.ensure_dirs()

    # Fetch
    fetcher = Fetcher(config)
    result = await fetcher.fetch("https://example.com", extract=True)
    print(result.title)
    await fetcher.close()

    # Search
    search = SearchEngine(config)
    results = await search.search("python async", max_results=5)
    for r in results:
        print(f"{r.position}. {r.title} - {r.url} ({r.backend})")
    await search.close()

    # Export to Markdown
    md = Exporter.search_to_markdown(results, title="Python Async Search")
    print(md)

    # Parse sitemap
    parser = SitemapParser(config)
    sitemap = await parser.fetch_sitemap("https://example.com/sitemap.xml")
    print(f"Found {sitemap.url_count} URLs")
    await parser.close()

asyncio.run(main())
```

## How it works

- **Search** tries Bing first, then DuckDuckGo HTML - both via direct HTTP scraping, no API key
- **Fetching** uses httpx with exponential-backoff retries, per-domain rate limiting, and 5 MB cap
- **Content extraction** uses trafilatura primary, readability-lxml automatic fallback
- **Caching** is SQLite with TTL and size cap; old entries evicted automatically
- **Crawling** is concurrent BFS with depth, page count, concurrency, same-domain, and robots.txt limits
- **Incremental crawling** only re-fetches changed pages using ETag/Last-Modified conditional requests
- **Sitemap support** parses sitemap.xml and sitemap indexes, discovers sitemaps via robots.txt
- **Export** converts results to JSON, CSV, or Markdown
- **Browser fingerprint rotation** random User-Agents + realistic headers to avoid anti-bot detection
- **Proxy support** route all HTTP/HTTPS requests through a proxy
- **TOML config** configure via `~/.config/webscout/config.toml` in addition to env vars

Everything runs locally. No data leaves your machine.

## Configuration

All settings have sensible defaults. Override via environment variables (`WEBSCOUT_` prefix), a TOML config file, or CLI flags.

### Config file

Create `~/.config/webscout/config.toml`:

```toml
[cache]
ttl = 7200
max_size_mb = 512

[fetch]
timeout = 15.0
max_retries = 3

[proxy]
http = "http://proxy:8080"
https = "http://proxy:8080"

[search]
max_results = 10
backends = ["bing", "duckduckgo"]

[crawler]
max_depth = 2
max_pages = 20
concurrency = 5
respect_robots = true

[logging]
level = "WARNING"
json = false
```

### Environment variables

| Variable | Default | What it does |
|---|---|---|
| `WEBSCOUT_CACHE_DIR` | `~/.cache/webscout` | Where the SQLite cache lives |
| `WEBSCOUT_CACHE_TTL` | `7200` | Cache entry lifetime in seconds |
| `WEBSCOUT_CACHE_MAX_SIZE_MB` | `512` | Max cache size before eviction |
| `WEBSCOUT_REQUEST_TIMEOUT` | `15.0` | HTTP timeout in seconds |
| `WEBSCOUT_MAX_RETRIES` | `3` | Retry attempts per request |
| `WEBSCOUT_RATE_LIMIT_PER_SECOND` | `2.0` | Max requests per second per domain |
| `WEBSCOUT_SEARCH_MAX_RESULTS` | `10` | Default search result count |
| `WEBSCOUT_SEARCH_BACKENDS` | `bing,duckduckgo` | Comma-separated backend order |
| `WEBSCOUT_CRAWLER_MAX_DEPTH` | `2` | Default crawl depth |
| `WEBSCOUT_CRAWLER_MAX_PAGES` | `20` | Default max pages per crawl |
| `WEBSCOUT_CRAWLER_CONCURRENCY` | `5` | Concurrent fetches per depth level |
| `WEBSCOUT_RESPECT_ROBOTS` | `true` | Whether crawler respects robots.txt |
| `WEBSCOUT_EXTRACT_OUTPUT_FORMAT` | `markdown` | Default extraction output format |
| `WEBSCOUT_PROXY_HTTP` | (empty) | HTTP proxy URL |
| `WEBSCOUT_PROXY_HTTPS` | (empty) | HTTPS proxy URL |
| `WEBSCOUT_LOG_LEVEL` | `WARNING` | Log verbosity |
| `WEBSCOUT_LOG_JSON` | `0` | Set to `1` for JSON-formatted logs |

## Transports

```bash
# stdio (default - works with Claude Code, Cursor, etc.)
webscout-mcp

# SSE (for remote or browser-based clients)
webscout-mcp serve --transport sse --host 0.0.0.0 --port 8000
```

## Changelog

### 0.4.0

- **Export module**: export search/fetch/crawl results to JSON, CSV, or Markdown
- **Sitemap support**: parse sitemap.xml and sitemap indexes, discover sitemaps via robots.txt
- **Incremental crawler**: only re-fetch changed pages using ETag/Last-Modified conditional requests
- **Browser fingerprint rotation**: random User-Agents + realistic headers to avoid anti-bot detection
- **New CLI commands**: `sitemap` (parse/discover sitemaps), `export` (export to JSON/CSV/Markdown)
- **GitHub Actions CI**: automated testing on Python 3.10/3.11/3.12 + auto-publish to PyPI
- **Code quality**: mypy type checking, ruff linting, black formatting, pre-commit hooks
- **New Python API**: `Exporter`, `SitemapParser`, `IncrementalCrawler`, `UserAgentRotator`

### 0.3.0

- **TOML config file support**: configure via `~/.config/webscout/config.toml`
- **HTTP/HTTPS proxy support**: route all requests through a proxy
- **Dual content extraction**: trafilatura primary, readability-lxml automatic fallback
- **Search result deduplication**: duplicate URLs removed, positions renumbered
- **Region-aware search**: `region` parameter now actually passed to Bing and DuckDuckGo
- **Crawler performance**: eliminated double-fetch per page - ~2x faster crawls
- **Better retry logic**: retries on all httpx errors and HTTP 5xx
- **Fixed content-type detection**: proper HTML/XML detection

### 0.2.0

- Multi-backend search: Bing + DuckDuckGo HTML with automatic failover
- Concurrent crawler with configurable parallelism
- robots.txt compliance (configurable, on by default)
- CLI subcommands: `search`, `fetch`, `crawl`, `serve`
- Structured logging with console and JSON formatters
- Custom exception hierarchy for better error handling

### 0.1.0

- Initial release: web_search, web_fetch, web_crawl, web_extract, cache_stats, cache_clear
- SQLite cache with TTL and size-based eviction
- Per-domain token-bucket rate limiting
- Exponential backoff retries
- trafilatura content extraction

## Development

```bash
git clone https://github.com/wxs-lang/webscout-mcp.git
cd webscout-mcp
pip install -e ".[dev]"
pytest

# Code quality
ruff check .
black .
mypy webscout_mcp/

# Pre-commit hooks
pre-commit install
pre-commit run --all-files
```

## License

MIT
