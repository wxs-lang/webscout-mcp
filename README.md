# webscout-mcp

> A smart web search & fetch **MCP server** with built-in caching, rate-limiting, and content extraction. Zero API keys required.

webscout-mcp gives any AI agent (Claude Code, Cursor, Codex, OpenCode, etc.) a single, polished interface for everything web-related: **search, fetch, crawl, and structured data extraction**. It's built for agents that need to look things up, read pages, and pull data — without burning API credits or leaking data to third-party services.

## Why this exists

Existing tools fall into two camps:

1. **Cloud services** (Firecrawl, Jina Reader, SerpAPI) — great quality, but you pay per request and your data leaves your machine.
2. **Raw libraries** (requests, BeautifulSoup) — free and local, but every agent reimplements caching, retries, rate-limiting, and content extraction from scratch.

webscout-mcp sits in the middle: it's a **local-first MCP server** that handles all the boring plumbing so your agent can focus on the actual task. All content stays on your machine, all requests are cached, and there's no per-query billing.

## Features

| Feature | Description |
|---|---|
| 🔍 **Web Search** | Bing search with no API key, safe-search, and result caching |
| 📄 **Smart Fetch** | Fetches a page and extracts the main article (via `trafilatura`) — strips nav, ads, sidebars |
| 🕷️ **Lightweight Crawler** | BFS crawl with depth, page-count, and same-domain limits |
| 🎯 **Structured Extraction** | Pull data from pages using CSS selectors, attributes, regex — output as JSON |
| 💾 **Built-in Cache** | SQLite cache with TTL and size limits — repeat queries cost nothing |
| ⏱️ **Rate Limiting** | Token-bucket limiter per domain — be polite, avoid getting blocked |
| 🔄 **Smart Retries** | Exponential backoff on transient failures |
| 📝 **Multiple Formats** | Output extracted content as Markdown, plain text, or HTML |
| 🔒 **Local-first** | Everything runs on your machine — no data leaves, no API keys, no bills |

## Installation

```bash
pip install webscout-mcp
```

Or install from source:

```bash
git clone https://github.com/wxs-lang/webscout-mcp.git
cd webscout-mcp
pip install -e .
```

Requires **Python 3.10+**.

## Quick Start

### As an MCP server (recommended)

Add to your MCP client config (e.g. Claude Code `~/.claude.json`):

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

Or with custom settings:

```json
{
  "mcpServers": {
    "webscout": {
      "command": "webscout-mcp",
      "args": ["--cache-ttl", "3600", "--cache-dir", "/tmp/webscout-cache"]
    }
  }
}
```

### As a Python library

```python
import asyncio
from webscout_mcp import Config, Fetcher, SearchEngine

async def main():
    config = Config.from_env()
    config.ensure_dirs()

    # Fetch a page with main content extraction
    fetcher = Fetcher(config)
    result = await fetcher.fetch("https://example.com", extract=True)
    print(result.title)
    print(result.content[:500])
    await fetcher.close()

    # Search the web
    search = SearchEngine(config)
    results = await search.search("python async programming", max_results=5)
    for r in results:
        print(f"{r.position}. {r.title} — {r.url}")

asyncio.run(main())
```

## MCP Tools

Once connected, the following tools are available to your AI agent:

### `web_search`
Search the web via Bing (no API key required).

**Parameters:**
- `query` (string, required) — Search query
- `max_results` (integer, default 10) — Number of results (1-25)
- `region` (string, default "wt-wt") — Region code (e.g. "us-en", "cn-zh")
- `safe_search` (boolean, default true) — Enable safe search

### `web_fetch`
Fetch a URL and extract main content.

**Parameters:**
- `url` (string, required) — URL to fetch
- `extract` (boolean, default true) — Extract main article content
- `output_format` (string, default "markdown") — "markdown", "text", or "html"
- `max_chars` (integer, default 8000) — Truncate content to this many chars
- `bypass_cache` (boolean, default false) — Skip cache and re-fetch

### `web_crawl`
Crawl a website with bounded depth and page count.

**Parameters:**
- `seed_url` (string, required) — Starting URL
- `max_depth` (integer, default 2) — Max link depth (0-5)
- `max_pages` (integer, default 10) — Max pages to crawl (1-50)
- `same_domain_only` (boolean, default true) — Restrict to same domain
- `extract` (boolean, default true) — Extract main content from each page

### `web_extract`
Extract structured data from a page using CSS selectors.

**Parameters:**
- `url` (string, required) — Page URL
- `rules` (string, required) — JSON array of extraction rules

**Rule format:**
```json
[
  {"name": "title", "selector": "h1"},
  {"name": "price", "selector": ".price", "regex": "\\$([\\d.]+)"},
  {"name": "links", "selector": "a.product", "attribute": "href", "multiple": true}
]
```

### `cache_stats`
Return cache statistics (entry count, size, TTL, limits).

### `cache_clear`
Clear all cached entries.

## Configuration

All settings can be configured via environment variables (prefix `WEBSCOUT_`):

| Variable | Default | Description |
|---|---|---|
| `WEBSCOUT_CACHE_DIR` | `~/.cache/webscout` | Cache directory |
| `WEBSCOUT_CACHE_TTL` | `7200` | Cache TTL in seconds (2h) |
| `WEBSCOUT_CACHE_MAX_SIZE_MB` | `512` | Max cache size in MB |
| `WEBSCOUT_REQUEST_TIMEOUT` | `15.0` | HTTP request timeout in seconds |
| `WEBSCOUT_MAX_RETRIES` | `3` | Max retry attempts |
| `WEBSCOUT_USER_AGENT` | webscout-mcp/0.1 | User-Agent string |
| `WEBSCOUT_RATE_LIMIT_PER_SECOND` | `2.0` | Requests per second per domain |
| `WEBSCOUT_SEARCH_MAX_RESULTS` | `10` | Default search result count |
| `WEBSCOUT_CRAWLER_MAX_DEPTH` | `2` | Default crawl depth |
| `WEBSCOUT_CRAWLER_MAX_PAGES` | `20` | Default max pages per crawl |

## Transports

webscout-mcp supports two MCP transports:

```bash
# stdio (default — works with Claude Code, Cursor, etc.)
webscout-mcp

# SSE (for remote / browser-based clients)
webscout-mcp --transport sse --host 0.0.0.0 --port 8000
```

## How it compares

| | webscout-mcp | Firecrawl | Jina Reader | Raw requests+BS4 |
|---|---|---|---|---|
| Search | ✅ Bing | ✅ paid | ❌ | ❌ |
| Content extraction | ✅ trafilatura | ✅ | ✅ | ❌ manual |
| Structured extraction | ✅ CSS selectors | ✅ | ❌ | ❌ manual |
| Crawling | ✅ bounded | ✅ | ❌ | ❌ manual |
| Caching | ✅ SQLite | ❌ | ❌ | ❌ manual |
| Rate limiting | ✅ per-domain | ✅ server-side | ✅ server-side | ❌ manual |
| API key required | ❌ | ✅ | ✅ (free tier) | ❌ |
| Data leaves machine | ❌ | ✅ | ✅ | ❌ |
| Cost | Free | Pay per request | Free tier + paid | Free |

## License

MIT
