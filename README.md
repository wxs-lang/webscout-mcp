# webscout-mcp

A smart web search and fetch MCP server. No API keys required.

## What it does

Exposes six tools to any MCP-compatible AI agent (Claude Desktop, Cursor, etc.):

- `web_search` - Search the web via Bing with automatic DuckDuckGo failover
- `web_fetch` - Fetch a URL and extract main article content (markdown/text/html)
- `web_crawl` - Concurrent BFS crawl with depth/page limits and robots.txt compliance
- `web_extract` - Structured data extraction via CSS selectors, attributes, and regex
- `cache_stats` - View local cache statistics
- `cache_clear` - Clear the local cache

## Install

```bash
pip install webscout-mcp
```

Requires Python 3.10+.

## Usage

### As an MCP server

Add to your MCP client config (e.g. Claude Desktop):

```json
{
  "mcpServers": {
    "webscout": {
      "command": "webscout-mcp",
      "args": ["serve"]
    }
  }
}
```

### Command line

```bash
# Search
webscout-mcp search "python asyncio" -n 5

# Fetch a page
webscout-mcp fetch https://example.com --format markdown

# Crawl a site
webscout-mcp crawl https://example.com --depth 2 --pages 10 --concurrency 5
```

## Configuration

All settings are controlled via environment variables:

| Variable | Default | Description |
|---|---|---|
| `WEBSCOUT_CACHE_TTL` | 7200 | Cache TTL in seconds |
| `WEBSCOUT_CACHE_MAX_SIZE_MB` | 512 | Max cache size |
| `WEBSCOUT_REQUEST_TIMEOUT` | 15.0 | HTTP request timeout |
| `WEBSCOUT_MAX_RETRIES` | 3 | Max retries with exponential backoff |
| `WEBSCOUT_USER_AGENT` | (built-in) | User-Agent string |
| `WEBSCOUT_RATE_LIMIT_PER_SECOND` | 2.0 | Per-domain rate limit |
| `WEBSCOUT_SEARCH_BACKENDS` | bing,duckduckgo | Search backend order |
| `WEBSCOUT_SEARCH_MAX_RESULTS` | 10 | Default max search results |
| `WEBSCOUT_CRAWLER_MAX_DEPTH` | 2 | Default crawl depth |
| `WEBSCOUT_CRAWLER_MAX_PAGES` | 20 | Default max pages |
| `WEBSCOUT_CRAWLER_CONCURRENCY` | 5 | Concurrent crawl fetches |
| `WEBSCOUT_RESPECT_ROBOTS` | true | Respect robots.txt |
| `WEBSCOUT_LOG_LEVEL` | WARNING | Log level (DEBUG/INFO/WARNING/ERROR) |
| `WEBSCOUT_LOG_JSON` | 0 | Set to 1 for JSON log format |

## Features

### Multi-backend search

Bing is the primary backend. If Bing fails or returns nothing, DuckDuckGo HTML is tried automatically. Configure the order with `WEBSCOUT_SEARCH_BACKENDS`.

### Concurrent crawling

Pages are fetched concurrently within each depth level using `asyncio.Semaphore`. Control concurrency with the `concurrency` parameter or `WEBSCOUT_CRAWLER_CONCURRENCY`.

### robots.txt compliance

The crawler checks robots.txt before fetching each page. Uses a fail-open policy (allows when robots.txt is unavailable). Disable with `WEBSCOUT_RESPECT_ROBOTS=false`.

### Structured logging

Console-colored logs by default. Set `WEBSCOUT_LOG_JSON=1` for JSON-formatted logs suitable for aggregation. Control verbosity with `WEBSCOUT_LOG_LEVEL`.

### Custom exceptions

Full exception hierarchy: `WebScoutError` -> `FetchError`, `SearchError`, `RobotsTxtError`, `ExtractionError`, `CrawlError`, with specific subclasses for timeout, HTTP errors, forbidden, not found, content too large, and all-backends-failed.

### Local cache

SQLite-backed cache with TTL and size-based eviction. Reduces redundant requests and speeds up repeated searches/fetches.

### Rate limiting

Token-bucket rate limiting per domain, configurable via environment variables.

### Retry with backoff

Exponential backoff retry for transient HTTP failures.

## Changelog

### v0.2.0

- Multi-backend search architecture (Bing + DuckDuckGo HTML with automatic failover)
- Concurrent crawler with `asyncio.Semaphore` and per-depth-level batching
- robots.txt compliance checker with per-domain caching and fail-open policy
- Custom exception hierarchy (13 exception classes)
- Structured logging system (console + JSON formatters, configurable via env vars)
- CLI subcommands: `search`, `fetch`, `crawl`, `serve`
- `web_crawl` now accepts `concurrency` parameter and reports `skipped_robots` count
- `web_search` results include `backend` field indicating which search engine was used
- 35 new tests (total 54)

### v0.1.0

- Initial release
- web_search (Bing HTML scraping)
- web_fetch (httpx + trafilatura content extraction)
- web_crawl (BFS with depth/page limits)
- web_extract (CSS selector + attribute + regex extraction)
- SQLite cache with TTL and size eviction
- Per-domain token-bucket rate limiting
- Exponential backoff retry
- URL normalization
- 19 unit tests

## License

MIT
