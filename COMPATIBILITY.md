# Compatibility & Stability Promise

> **Version**: v0.9.0
> **Status**: Frozen for v1.0
> **Last updated**: 2026-09-06

This document defines the stable, frozen interfaces of webscout-mcp.
These interfaces will not change in backwards-incompatible ways until
v2.0.0. Agents and integrations can rely on these being stable.

---

## 1. MCP Tools (Frozen)

The following 11 MCP tools are frozen. Their names, parameter schemas,
and return structure will remain backwards-compatible.

### Core Web Tools

#### `web_search`
Search the web with automatic fallback across providers.

**Parameters:**
- `query` (string, required): Search query
- `max_results` (integer, optional, default=10): Max results (1-25)
- `region` (string, optional, default="wt-wt"): Search region
- `safe_search` (boolean, optional, default=true): Safe search filter

**Returns:** JSON string with structured search results.

#### `web_fetch`
Fetch a single URL and extract main content.

**Parameters:**
- `url` (string, required): URL to fetch
- `max_length` (integer, optional): Max content length in chars

**Returns:** JSON string with extracted content, metadata, and status.

#### `web_crawl`
Crawl a website with depth/page limits.

**Parameters:**
- `url` (string, required): Starting URL
- `max_depth` (integer, optional): Max crawl depth
- `max_pages` (integer, optional): Max pages to crawl
- `same_domain_only` (boolean, optional): Restrict to same domain

**Returns:** JSON string with crawled pages and results.

#### `web_extract`
Extract structured data from a page using CSS selectors.

**Parameters:**
- `url` (string, required): URL to extract from
- `rules` (string, required): JSON string of extraction rules

**Returns:** JSON string with extracted structured data.

### Cache Management

#### `cache_stats`
Show cache statistics.

**Parameters:** None

**Returns:** JSON string with cache size, hit rate, entries, etc.

#### `cache_clear`
Clear all cached entries.

**Parameters:** None

**Returns:** JSON string with number of entries deleted.

### Health & Monitoring

#### `search_health`
Get health report for all search backends and dynamic routing.

**Parameters:** None

**Returns:** JSON string with:
- `active_search_path`: Current active search path
- `service_statistics`: Request counts, fallback rate, error rate
- `dynamic_routing`: Provider scores, success rates, latencies, cost tiers
- Per-provider circuit breaker status

### Content Analysis

#### `metadata_extract`
Extract page metadata (JSON-LD, OpenGraph, Twitter Cards).

**Parameters:**
- `url` (string, required): URL to extract metadata from

**Returns:** JSON string with extracted metadata.

#### `rss_parse`
Parse RSS/Atom feeds and return entries.

**Parameters:**
- `url` (string, required): RSS/Atom feed URL

**Returns:** JSON string with feed entries.

#### `content_quality`
Analyze content quality (readability, keyword density, structure).

**Parameters:**
- `url` (string, required): URL to analyze
- `content` (string, optional): Content to analyze (instead of fetching)

**Returns:** JSON string with quality scores and analysis.

#### `broken_links`
Check for broken links on a web page.

**Parameters:**
- `url` (string, required): URL to check

**Returns:** JSON string with broken links and status codes.

---

## 2. Standard Error Codes (Frozen)

These error codes are stable and will not change. Agents can rely on
them for decision-making.

### Fetch Errors
- `FETCH_TIMEOUT` - Request timed out
- `FETCH_FORBIDDEN` - 403 Forbidden
- `FETCH_RATE_LIMITED` - 429 Too Many Requests
- `FETCH_ROBOTS_DENIED` - Blocked by robots.txt
- `FETCH_JS_REQUIRED` - Page requires JavaScript
- `FETCH_NOT_FOUND` - 404 Not Found
- `FETCH_SERVER_ERROR` - 5xx Server Error
- `FETCH_SSL_ERROR` - SSL/TLS error
- `FETCH_DNS_ERROR` - DNS resolution failed
- `FETCH_CONNECTION_ERROR` - Connection failed
- `FETCH_CONTENT_TOO_LARGE` - Content exceeds max size
- `FETCH_REDIRECT_ERROR` - Redirect loop or invalid redirect

### Search Errors
- `SEARCH_BACKEND_FAILED` - Single search backend failed
- `SEARCH_ALL_BACKENDS_FAILED` - All search backends failed
- `SEARCH_RATE_LIMITED` - Search rate limited
- `SEARCH_TIMEOUT` - Search timed out
- `SEARCH_INVALID_QUERY` - Invalid search query
- `SEARCH_EMPTY_RESULTS` - Search returned no results
- `SEARCH_CIRCUIT_OPEN` - Circuit breaker is open

### Content Errors
- `CONTENT_EMPTY` - Content is empty
- `CONTENT_UNSUPPORTED` - Unsupported content type
- `CONTENT_PARSE_ERROR` - Failed to parse content
- `CONTENT_EXTRACTION_FAILED` - Content extraction failed

### Crawl Errors
- `CRAWL_DEPTH_EXCEEDED` - Max crawl depth exceeded
- `CRAWL_PAGES_EXCEEDED` - Max pages exceeded
- `CRAWL_ROBOTS_DENIED` - Blocked by robots.txt

### Security Errors
- `SECURITY_SSRF_BLOCKED` - SSRF attempt blocked
- `SECURITY_INVALID_URL` - Invalid URL
- `SECURITY_PRIVATE_IP_BLOCKED` - Private IP blocked

### System Errors
- `SYSTEM_ERROR` - Generic system error
- `SYSTEM_CONFIG_ERROR` - Configuration error
- `SYSTEM_UNAVAILABLE` - System unavailable

---

## 3. Configuration (Frozen)

### Environment Variables

All environment variables are stable and will not be renamed.

#### Core
- `WEBSCOUT_CACHE_DIR` - Cache directory path
- `WEBSCOUT_CACHE_TTL` - Cache TTL in seconds (default: 7200)
- `WEBSCOUT_CACHE_MAX_SIZE_MB` - Max cache size in MB (default: 512)
- `WEBSCOUT_REQUEST_TIMEOUT` - Request timeout in seconds (default: 15)
- `WEBSCOUT_MAX_RETRIES` - Max retries (default: 3)
- `WEBSCOUT_USER_AGENT` - Custom user agent
- `WEBSCOUT_MAX_CONTENT_LENGTH` - Max content length in bytes

#### Proxy
- `WEBSCOUT_PROXY_HTTP` - HTTP proxy URL
- `WEBSCOUT_PROXY_HTTPS` - HTTPS proxy URL

#### Rate Limiting
- `WEBSCOUT_RATE_LIMIT_PER_SECOND` - Requests per second (default: 2.0)
- `WEBSCOUT_RATE_LIMIT_BURST` - Burst size (default: 5)

#### Search
- `WEBSCOUT_SEARCH_MAX_RESULTS` - Max search results (default: 10)
- `WEBSCOUT_SEARCH_BACKENDS` - Comma-separated backend list
- `WEBSCOUT_SEARCH_MERGE_BACKENDS` - Merge results from all backends
- `WEBSCOUT_SEARCH_CIRCUIT_FAILURE_THRESHOLD` - Circuit breaker threshold
- `WEBSCOUT_SEARCH_CIRCUIT_RECOVERY_TIME` - Circuit recovery time in seconds

#### Optional API Keys (Stable names)
- `SERPAPI_API_KEY` - SerpAPI key (optional, stable fallback)
- `TAVILY_API_KEY` - Tavily key (optional, stable fallback)

#### Crawler
- `WEBSCOUT_CRAWLER_MAX_DEPTH` - Max crawl depth (default: 2)
- `WEBSCOUT_CRAWLER_MAX_PAGES` - Max pages (default: 20)
- `WEBSCOUT_CRAWLER_CONCURRENCY` - Concurrent requests (default: 5)
- `WEBSCOUT_CRAWLER_DELAY` - Delay between requests
- `WEBSCOUT_RESPECT_ROBOTS` - Respect robots.txt (default: true)

#### Logging
- `WEBSCOUT_LOG_LEVEL` - Log level (default: WARNING)
- `WEBSCOUT_LOG_JSON` - JSON log format (default: false)

---

## 4. Deprecation Policy

- **Deprecated features** will be marked with `DeprecationWarning` for at least 2 minor versions before removal.
- **New features** will be added in minor versions (0.x.0) and will not break existing functionality.
- **Bug fixes** will be released in patch versions (0.0.x).
- **Breaking changes** will only occur in major versions (x.0.0).

---

## 5. Cross-Platform Support

### Supported Platforms
- **Linux**: Ubuntu 20.04+, Debian 11+, CentOS 8+
- **macOS**: 11+ (Intel and Apple Silicon)
- **Windows**: 10+ (PowerShell and WSL2)

### Python Versions
- Python 3.10 ✅
- Python 3.11 ✅
- Python 3.12 ✅

### Platform-Specific Notes
- **Windows**: Use `python -m webscout_mcp serve` (not `python3`)
- **macOS**: Apple Silicon (M1/M2/M3) fully supported via arm64 wheels
- **Linux**: Headless servers supported, no browser required for core functionality

---

## 6. Versioning

We follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (x.0.0): Breaking changes to frozen interfaces
- **MINOR** (0.x.0): New features, backwards-compatible
- **PATCH** (0.0.x): Bug fixes, backwards-compatible

Current frozen state: **v0.9.0** → Target: **v1.0.0** (stable release)
