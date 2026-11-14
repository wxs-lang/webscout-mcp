# Compatibility & Stability Promise

> **Version**: v1.4.0
> **Status**: Frozen interfaces, backward-compatible
> **Last updated**: 2026-09-23

This document defines the stable, frozen interfaces of webscout-mcp.
These interfaces will not change in backwards-incompatible ways until
v2.0.0. Agents and integrations can rely on these being stable.

---

## 1. MCP Tools (Frozen)

The following 17 MCP tools are frozen. Their names, parameter schemas,
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

Stable fields (present on every response):
- `query` (string): Echoed query
- `count` (integer): Number of results returned
- `results` (array): Search result objects

**v1.4.0 additive fields** (backwards-compatible; old consumers may ignore):
- `status` (string): `success`, `empty`, or `error`
- `error` (object, only when `status="error"`): `{code, message, retryable?}`

Empty/whitespace queries return `status="error"` with `code="SEARCH_INVALID_QUERY"` and make zero provider network calls. Internal route_trace is not exposed in the normal MCP response.

#### `web_fetch`
Fetch a single URL and extract main content, returning one window of the article plus a continuation block.

**Parameters:**
- `url` (string, required): URL to fetch
- `extract` (boolean, optional, default=true): Run content extraction
- `output_format` (string, optional, default="markdown"): `markdown`, `text`, or `html`
- `max_chars` (integer, optional, default=8000): Target size of the returned window in chars (not a hard cap on how much is fetched)
- `bypass_cache` (boolean, optional, default=false): Ignore response cache and content snapshot
- `start_char` (integer, optional, default=0): **Added in v1.3.0**, backwards-compatible. Offset into the already-extracted content; use `continuation.next_start_char` to read the next window.

> Note: the legacy `max_length` parameter name is **deprecated/removed**; the current parameter is `max_chars`.

**Returns:** JSON string with extracted content, metadata, and status. When more content remains, the response includes an additive `continuation` object (`has_more`, `start_char`, `end_char`, `next_start_char`, `total_chars`, `remaining_chars`, `served_from_snapshot`). Agents that ignore it behave exactly as before; the field is purely additive.

**v1.10.0 additive fields** (backwards-compatible; old consumers may ignore):

- `error_code` (string or null): the standard error taxonomy code for a failed
  fetch, e.g. `FETCH_NOT_FOUND`, `FETCH_SERVER_ERROR`, `FETCH_CONNECTION_ERROR`.
  Null on success. Before this, a caller saw only `status_code` and could not
  distinguish a missing page from a rate limit without parsing prose.
- `retryable` (boolean, always present): whether repeating the same request could
  plausibly succeed. A 4xx is `false`; a 5xx, timeout, rate limit or connection
  failure is `true`.
- `extraction_status` (string or null): `"ok"` when text was extracted,
  `"empty"` when an extractor ran but the page yielded too little, `"unavailable"`
  when no extractor could be imported. Null when extraction was not requested.
  `extracted: false` alone could not tell an environment fault from a page that
  simply had no article - and in the `unavailable` case the caller was receiving
  raw HTML while having asked for markdown.

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

#### `web_extract_schema`
Extract data matching a JSON Schema without writing selectors.

Where `web_extract` requires you to know the page's class names, this takes the shape you
want and resolves each field itself, best source first: `json-ld` (the page's own structured
data), then `meta` (OpenGraph / Twitter cards), then `semantic-html` (`<h1>`, `<time>`,
`itemprop`, narrow class hints). Derivation, not an LLM - no key, no per-call cost,
deterministic.

**Parameters:**
- `url` (string, required): URL to extract from
- `schema` (string, required): JSON Schema, e.g.
  `{"type": "object", "properties": {"price": {"type": "number"}}}`

**Returns:** JSON with `data`, per-field `sources`, `missing` (explicit, never a silent
null), and `resolved`/`requested` counts.

**Note on the tradeoff:** a field this cannot place comes back `null` with an empty source.
It will not invent a plausible value - `sources` exists so a caller can tell a value the page
stated from one that was inferred.

**Stability: beta.** The resolution order and the response shape are stable; the set of
class-name hints and the semantic heuristics will keep changing as pages are measured. Callers
that need exact extraction should use `web_extract` with selectors, which does not infer.

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

#### ecovery_policyGet the fetch recovery policy table as data.

**Parameters:** None

**Returns:** JSON string with \policy_markdown\ (the rendered table:
thresholds, marker sets, reason→action rules, classification stages) and
\warnings\ (drift findings from assembling it).

**Stability: beta.** The table is the single source the recovery classifier
modules bind their thresholds to (identity-tested); the rendered shape may
gain sections as the policy grows.

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

### Content Understanding

#### `web_knowledge_graph`

Build a knowledge graph of entities and relationships from a page or from text.

**Parameters:**
- `url` (string, optional): page to fetch first
- `text` (string, optional): text to analyse directly
- `max_entities` (integer, default `50`): cap on returned entities
- `include_centrality` (boolean, default `true`): include the centrality ranking

Exactly one of `url` or `text` must be supplied; passing neither returns an explicit
error rather than an empty graph.

**Returns:** JSON string with `entities`, `relationships`, `stats`, `notes`, and
`top_entities_by_centrality` when enabled.

**Stability: beta.** The extraction is rule-based, not model-based, and the response
says so in its `notes` field:

- relationships are proximity-derived and always typed `co_occurs_with`; there is no
  sentence-level semantic parsing yet
- entity types come from suffix and keyword patterns. A word the patterns cannot
  classify is reported as `unknown` rather than guessed, and a known technology
  keyword upgrades it to `technology`

Frozen: the tool name and the parameter schema. Not frozen: the entity and
relationship payload shape, which may gain fields (the same additive precedent as
`error_code` / `retryable` / `extraction_status`).

#### `web_rag_context`

Retrieve the passages of a page most relevant to a query, compressed to fit a context
window.

**Parameters:**
- `url` (string, optional): page to fetch first
- `text` (string, optional): text to analyse directly
- `query` (string, required): what to retrieve passages about
- `top_k` (integer, default `5`): number of passages returned
- `max_chunk_size` (integer, default `60`): words per passage

Exactly one of `url` or `text` must be supplied, plus `query`.

**Returns:** JSON string with `passages` (each carrying `chunk_id`, `score`, `words`,
`text`), `compressed_context`, `stats`, `retrieval_score`, `confidence`, and `notes`.

**Stability: beta.** Ranking is lexical, not semantic:

- passages are ranked by stop-word-filtered IDF over content terms; there is no
  embedding model, so a query phrased with different vocabulary than the document will
  miss. Synonyms do not match.
- the default `max_chunk_size` of 60 words is deliberately small. At the library
  default of 500 a normal article stays a single passage and there is nothing to rank;
  measured retrieval went from 0/5 to 5/5 on a probe set after this change.
- passages are sentence-aligned, so each one reads as complete sentences.

`compressed_context` is the field intended to be handed to a model; `passages` are for
inspection and citation.

Frozen: the tool name and the parameter schema. Not frozen: the passage payload shape.

#### `web_compare_sites`

Compare several websites side by side on SEO, performance, content and links.

**Parameters:**
- `urls` (array of strings, required): 1 to 10 pages to compare
- `names` (array of strings, optional): labels, same length as `urls`

**Returns:** JSON string with `sites` (each with per-axis and overall scores), a
`comparison_matrix` of 15 metrics across sites, `winner`, `recommendations`, `summary`,
and `failures` for URLs that could not be fetched.

**Stability: beta.** The scores are heuristics, and the response says so in its `notes`:

- each axis is 0-100 from hand-written thresholds, not a search engine's ranking
- metrics come from a plain HTTP fetch, so a JavaScript-rendered page can look thin when
  it is not; that shows up as a low content score rather than an error
- an unfetchable URL appears in `failures` with its recovery reason instead of aborting
  the comparison, so one dead competitor cannot sink the other nine

Frozen: the tool name and the parameter schema. Not frozen: the metric payload shape.

#### `web_monitor`

Check a URL for changes since the last check, and return what changed.

**Parameters:**
- `url` (string, required): page to check
- `ignore_text` (array of strings, optional): regexes removed before comparing, for values that change every request
- `ignore_selector` (array of strings, optional): CSS selectors whose subtrees are excluded
- `price_selector` (string, optional): CSS selector for a price to track
- `price_change_threshold` (float, default `0.0`): minimum fractional move to report, e.g. `0.05` for 5%
- `min_change_size` (integer, default `10`): characters that must differ before a text change counts
- `keywords_appear` (array of strings, optional): report when these appear
- `include_diff` (boolean, default `true`): include a unified diff
- `state_path` (string, optional): where the snapshot lives; defaults to `~/.cache/webscout/monitor_history.json`
- `json_path` (string, optional): watch one value inside a JSON response. `json:$.a.b` uses JSONPath, `jq:.a.b` uses jq. Requires the `[json]` extra

**Returns:** JSON string with `changes`, `change_count`, `baseline_established`,
`state_path` and `notes`.

**Stability: beta**, with two behaviours a caller must know:

- **it checks once per call and does not schedule itself.** Monitoring continuously
  requires the MCP client or an external scheduler to call it again. A user who sets it
  once and expects automatic tracking would reasonably conclude it is broken.
- **the first call for a URL only records a baseline** and reports no changes, signalled
  by `baseline_established: true`.
- **`json_path` reduces the response to one value before comparing.** That is the point:
  a JSON API's neighbours and formatting churn while the watched field does not, so
  watching `$.product.price` is stable where watching the body is not. `json:` needs the
  `jsonpath` package and `jq:` needs `jq`; both come from the `[json]` extra, and a
  selector for an uninstalled language fails with the install command rather than an
  obscure error.
- **a malformed JSONPath is rejected rather than silently watching everything.**
  Measured: the `jsonpath` library degrades bad syntax like `$[[[` into a wildcard and
  returns the whole document plus its nodes. The signature - the document appearing first
  in a multi-match result - is detected and refused.

State persists to disk between calls, because the comparison baseline is written
alongside the change log. Without that the tool could never report a change - see the
v2.1.0 note below.

Frozen: the tool name and the parameter schema. Not frozen: the change payload shape.

Note on a scoring change this release: readability used to contribute up to 35 points
without a minimum body length, which made a 6-word stub (readability 88) outscore a
667-word article (readability 30). Readability now only contributes once a page has at
least 100 words. Scores for very short pages are therefore lower than in earlier
versions; for substantial pages nothing changed.

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

Current frozen state: **v1.4.0**. Interfaces remain backward-compatible until v2.0.0.
