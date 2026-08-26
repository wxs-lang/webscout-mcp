# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-08-26

### Added
- **Export module**: export search/fetch/crawl results to JSON, CSV, or Markdown
- **Sitemap support**: parse sitemap.xml and sitemap indexes, discover sitemaps via robots.txt
- **Incremental crawler**: only re-fetch changed pages using ETag/Last-Modified conditional requests
- **Browser fingerprint rotation**: random User-Agents + realistic headers to avoid anti-bot detection
- **New CLI commands**: `sitemap` (parse/discover sitemaps), `export` (export to JSON/CSV/Markdown)
- **GitHub Actions CI**: automated testing on Python 3.10/3.11/3.12 + auto-publish to PyPI
- **Code quality**: mypy type checking, ruff linting, black formatting, pre-commit hooks
- **New Python API**: `Exporter`, `SitemapParser`, `IncrementalCrawler`, `UserAgentRotator`

### Fixed
- Fixed `__init__.py` hard import of server module (now optional, avoids crash when mcp not installed)
- Fixed TestServer tests to skip when mcp library is unavailable or version-incompatible
- Fixed test_v2.py import error (`_build_parser` -> `build_parser`)
- Removed pytest-asyncio dependency, converted async tests to `asyncio.run()` for better compatibility

## [0.3.0] - 2026-08-26

### Added
- **TOML config file support**: configure via `~/.config/webscout/config.toml` in addition to env vars
- **HTTP/HTTPS proxy support**: route all requests through a proxy
- **Dual content extraction**: trafilatura primary, readability-lxml automatic fallback
- **Search result deduplication**: duplicate URLs removed, positions renumbered
- **Region-aware search**: `region` parameter now actually passed to Bing and DuckDuckGo

### Improved
- **Crawler performance**: eliminated double-fetch per page — ~2x faster crawls
- **Better retry logic**: retries on all httpx errors and HTTP 5xx
- **Fixed content-type detection**: proper HTML/XML detection

## [0.2.0] - 2026-08-26

### Added
- Multi-backend search: Bing + DuckDuckGo HTML with automatic failover
- Concurrent crawler with configurable parallelism
- robots.txt compliance (configurable, on by default)
- CLI subcommands: `search`, `fetch`, `crawl`, `serve`
- Structured logging with console and JSON formatters
- Custom exception hierarchy for better error handling
- New config: `WEBSCOUT_SEARCH_BACKENDS`, `WEBSCOUT_CRAWLER_CONCURRENCY`, `WEBSCOUT_RESPECT_ROBOTS`

## [0.1.0] - 2026-08-26

### Added
- Initial release: web_search, web_fetch, web_crawl, web_extract, cache_stats, cache_clear
- SQLite cache with TTL and size-based eviction
- Per-domain token-bucket rate limiting
- Exponential backoff retries
- trafilatura content extraction

[0.4.0]: https://github.com/wxs-lang/webscout-mcp/releases/tag/v0.4.0
[0.3.0]: https://github.com/wxs-lang/webscout-mcp/releases/tag/v0.3.0
[0.2.0]: https://github.com/wxs-lang/webscout-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/wxs-lang/webscout-mcp/releases/tag/v0.1.0
