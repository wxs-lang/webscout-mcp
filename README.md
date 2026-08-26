# webscout-mcp

Web search and fetch tools for AI agents, as an MCP server. Search, fetch, crawl, and extract structured data from the web — no API keys, no per-request billing, everything stays on your machine.

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

- `web_search` — search via Bing, no key needed
- `web_fetch` — fetch a page and extract the main article (markdown/text/html)
- `web_crawl` — bounded BFS crawl with depth and page limits
- `web_extract` — pull structured data with CSS selectors, attributes, regex
- `cache_stats` — inspect the local cache
- `cache_clear` — wipe the cache

## Usage examples

### Search

```json
web_search(query="best python async libraries", max_results=5)
```

Returns structured results with title, URL, and snippet.

### Fetch a page

```json
web_fetch(url="https://example.com", extract=true, output_format="markdown")
```

`extract=true` runs trafilatura to strip nav, ads, and sidebars — you get clean article content, not raw HTML.

### Extract structured data

```json
web_extract(
  url="https://example.com/products",
  rules='[
    {"name": "titles", "selector": ".product h2", "multiple": true},
    {"name": "prices", "selector": ".price", "regex": "\\$([\\d.]+)", "multiple": true},
    {"name": "links", "selector": "a.product", "attribute": "href", "multiple": true}
  ]'
)
```

Each rule supports `selector`, `attribute`, `multiple`, `regex`, and `default`.

### Crawl a site

```json
web_crawl(seed_url="https://example.com", max_depth=2, max_pages=10)
```

Respects same-domain by default. All fetched pages go through the same cache and rate limiter.

## Use as a Python library

```python
import asyncio
from webscout_mcp import Config, Fetcher, SearchEngine

async def main():
    config = Config.from_env()
    config.ensure_dirs()

    fetcher = Fetcher(config)
    result = await fetcher.fetch("https://example.com", extract=True)
    print(result.title)
    print(result.content[:500])
    await fetcher.close()

    search = SearchEngine(config)
    results = await search.search("python async", max_results=5)
    for r in results:
        print(f"{r.position}. {r.title} — {r.url}")

asyncio.run(main())
```

## How it works

- **Search** uses Bing via direct HTTP (no API key). Results are cached by query.
- **Fetching** uses httpx with exponential-backoff retries, per-domain token-bucket rate limiting, and a 5 MB content cap.
- **Content extraction** uses trafilatura — the same library behind many read-it-later services.
- **Caching** is SQLite with TTL and a size cap; old entries are evicted automatically. Repeat fetches and searches cost nothing.
- **Crawling** is BFS with configurable depth, page count, and same-domain restriction.

Everything runs locally. No data leaves your machine.

## Configuration

All settings have sensible defaults. Override via environment variables (`WEBSCOUT_` prefix) or CLI flags:

| Variable | Default | What it does |
|---|---|---|
| `WEBSCOUT_CACHE_DIR` | `~/.cache/webscout` | Where the SQLite cache lives |
| `WEBSCOUT_CACHE_TTL` | `7200` | Cache entry lifetime in seconds |
| `WEBSCOUT_CACHE_MAX_SIZE_MB` | `512` | Max cache size before eviction |
| `WEBSCOUT_REQUEST_TIMEOUT` | `15.0` | HTTP timeout in seconds |
| `WEBSCOUT_MAX_RETRIES` | `3` | Retry attempts per request |
| `WEBSCOUT_RATE_LIMIT_PER_SECOND` | `2.0` | Max requests per second per domain |
| `WEBSCOUT_SEARCH_MAX_RESULTS` | `10` | Default search result count |
| `WEBSCOUT_CRAWLER_MAX_DEPTH` | `2` | Default crawl depth |
| `WEBSCOUT_CRAWLER_MAX_PAGES` | `20` | Default max pages per crawl |

CLI flags override env vars:

```bash
webscout-mcp --cache-ttl 3600 --cache-dir /tmp/webscout
```

## Transports

```bash
# stdio (default — works with Claude Code, Cursor, etc.)
webscout-mcp

# SSE (for remote or browser-based clients)
webscout-mcp --transport sse --host 0.0.0.0 --port 8000
```

## Development

```bash
git clone https://github.com/wxs-lang/webscout-mcp.git
cd webscout-mcp
pip install -e ".[dev]"
pytest
```

## License

MIT
