# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-06

### 🎉 First Stable Release

After extensive development, testing, and real-world validation, webscout-mcp reaches v1.0.0 stable.

### ✨ Key Features
- **11 stable MCP tools** for web research
- **Dynamic provider routing** with health-based scoring
- **Multi-backend search** with automatic failover (Bing → DuckDuckGo → Tavily)
- **Circuit breaker** per provider with automatic recovery
- **Startup self-check** for reliability verification
- **Comprehensive test suite** (unit, integration, MCP E2E, fault injection, live)
- **Full CI/CD** with quality gates and automated releases
- **Cross-platform support** (Linux, macOS, Windows)
- **Stability contract** with frozen APIs and error codes

### 📦 Installation
```bash
pip install webscout-mcp==1.0.0
```

### 🚀 Quick Start
```bash
# Start MCP server
python -m webscout_mcp serve

# Verify installation
python scripts/verify_installation.py
```

### 🔧 MCP Tools (11)
- `web_search` - Search with automatic fallback
- `web_fetch` - Fetch and extract page content
- `web_crawl` - Crawl websites with depth limits
- `web_extract` - Extract structured data via CSS selectors
- `cache_stats` - View cache statistics
- `cache_clear` - Clear cache
- `search_health` - Provider health and dynamic routing status
- `metadata_extract` - Extract page metadata
- `rss_parse` - Parse RSS/Atom feeds
- `content_quality` - Analyze content quality
- `broken_links` - Check for broken links

### 📚 Documentation
- [README.md](README.md) - Full documentation
- [COMPATIBILITY.md](COMPATIBILITY.md) - Stability contract and frozen APIs
- [SECURITY.md](SECURITY.md) - Security policy
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contributing guide

---

## [0.9.0] - 2026-09-06

### ✨ Added
- **COMPATIBILITY.md** - Formal stability contract documenting frozen APIs
  - 11 MCP tools with frozen names, schemas, and return structures
  - 40+ standard error codes
  - 30+ environment variables with stable names
  - Deprecation policy (2 minor version warning period)
  - Semantic versioning commitment
- **Cross-platform verification script** (`scripts/verify_installation.py`)
  - 12 checks covering imports, server creation, SearchService, config, errors
  - Platform detection (Linux/macOS/Windows)
  - Exit code 0 for all pass, 1 for failures
- **Platform support matrix**: Linux (Ubuntu/Debian/CentOS), macOS 11+ (Intel/Apple Silicon), Windows 10+
- **Python support**: 3.10, 3.11, 3.12

### 🔧 Changed
- API/configuration freeze point for v1.0.0 stability
- All interfaces documented and frozen for backwards compatibility

---

## [0.8.1] - 2026-09-06

### ✨ Added
- **Expanded live E2E test scenarios** from 15 to 20 search queries
  - English technical (5): python, github, postgresql, fastapi, docker
  - English news (3): tech news, python release, open source ai
  - English github (2): mcp server example, fastapi repo
  - Chinese technical (5): corresponding Chinese queries
  - Chinese news (3): tech news, AI trends, open source software
  - Chinese general (2): exam books, grad school math
- **Expanded fetch URLs** from 5 to 10
  - Technical docs (5)
  - News sites (2): Hacker News, Python blog
  - GitHub repo (1): fastapi
  - Redirect page (1): httpbin
  - JS-heavy page (1): python.org
- **Categorized reporting** in live test results
  - `search_by_category`: success rate and latency per query category
  - `fetch_by_category`: success rate and latency per URL category
  - Enables long-term tracking of scenario-specific stability

---

## [0.8.0] - 2026-09-06

### ✨ Added
- **Dynamic Provider Router** (`provider_router.py`)
  - Replaces fixed-order fallback with intelligent health-based selection
  - ProviderHealthScorer calculates 0-100 score per provider
  - Weighted scoring: success rate (40%), latency (25%), error rate (20%), circuit state (15%)
  - Rolling 24h metrics window with P50/P95 latency tracking
  - Error type taxonomy: 429, 403, timeout, connection, other
- **Cost-aware routing**
  - ProviderCostTier: FREE, LOW_COST, PAID, PREMIUM
  - `prefer_free` mode: free providers get small score boost when scores are close
  - Paid providers (Tavily) only used when free providers are degraded
- **Provider metrics tracking**
  - Rolling request/success/error history (1000 entries)
  - P50/P95 latency calculation
  - Error type breakdown
  - Circuit state tracking (open/half-open/closed)
- **Enhanced health report** in `search_health` tool
  - `dynamic_routing` section with ranked providers
  - Per-provider scores, success rates, latencies, cost tiers
  - Detailed reasons for each score

### 🔧 Changed
- SearchService now uses dynamic routing by default
- Tavily provider integrated as PAID tier fallback
- Bing/DuckDuckGo as FREE tier primary providers

---

## [0.7.1] - 2026-09-06

### 🔧 Fixed
- **Ruff G201**: Use `log.exception()` instead of `log.error(..., exc_info=True)` in tavily_provider.py
- **Lint cleanup**: Fixed F541 (f-string without placeholders) in examples/ and tests/
- **All GitHub Actions** updated to latest versions (checkout@v4, setup-python@v5, upload-artifact@v4)

### ✨ Added
- Code Quality workflow now fully green (Ruff, Mypy, Bandit, CodeQL all pass)

---

## [0.7.0] - 2026-09-06

### ✨ Added
- **Startup Self-Check** (`startup_check.py`)
  - 5 checks run at MCP server startup: cache, search_engine, search_service, fetcher, search_connectivity
  - Runs in background (non-blocking, does not delay server start)
  - Each check tracks duration, pass/fail status, and detailed message
  - Startup report included in `search_health` tool response
- **Tavily Search API Provider** (`tavily_provider.py`)
  - Stable API-based search designed specifically for AI agents
  - No HTML scraping, no DOM/CAPTCHA/Bot detection risk
  - Auto-detects `TAVILY_API_KEY` environment variable
  - Full error handling: 401, 429, 5xx, timeout, connection error
  - Integrated as 3rd fallback in SearchService (Bing → DuckDuckGo → Tavily)
  - Circuit breaker and health tracking work automatically
- **New config options**: `TAVILY_API_KEY`, `TAVILY_TIMEOUT`

### 🔧 Changed
- SearchService fallback chain: Bing → DuckDuckGo → Tavily (when API key configured)
- Free providers remain primary, paid Tavily only used when needed

---

## [0.6.0] - 2026-09-02

### ⚠️ BREAKING CHANGES
- MCP server startup command changed from `python -m webscout_mcp.server` to `python -m webscout_mcp serve`
- Experimental features (RAG, Knowledge Graph, AI Optimizer, SEO, OCR, PDF, Monitor, etc.) moved to `extras/` directory

### ✨ Added
- **5 new MCP tools** (total 11):
  - `search_health` - Get health report for all search backends (circuit breaker status)
  - `metadata_extract` - Extract page metadata (JSON-LD, OpenGraph, Twitter Cards)
  - `rss_parse` - Parse RSS/Atom feeds and return entries
  - `content_quality` - Analyze content quality (readability, keyword density, structure)
  - `broken_links` - Check for broken links on a web page

- **New Search Architecture**:
  - `SearchService` + `SearchProvider` standardized interface
  - Search backends: Bing HTML, DuckDuckGo HTML, SerpAPI (optional)
  - Automatic failover between search backends
  - Circuit breaker per backend (OPEN/HALF_OPEN/CLOSED states)
  - Provider health monitoring and statistics

- **Comprehensive Test Suite**:
  - Unit tests (100+ tests)
  - Integration tests
  - MCP protocol-level E2E tests (deterministic, required CI)
  - MCP Live E2E tests (real network, scheduled)
  - System-level fault injection tests
  - Live Network Tests (scheduled daily, 15 searches + 5 fetches)
  - Coverage reporting

- **CI/CD Infrastructure**:
  - Python 3.10 / 3.11 / 3.12 test matrix
  - Ruff linting (enforced)
  - Mypy type checking (enforced)
  - Bandit security scanning (enforced for medium/high severity)
  - CodeQL security analysis
  - Docker image build and publish
  - Automated Release Gate (waits for all required checks)
  - Main branch protection with required status checks

- **Error Handling**:
  - Standardized error hierarchy (30+ error classes)
  - Structured error responses: `{code, provider, retryable, message}`
  - Error codes: FETCH_TIMEOUT, FETCH_FORBIDDEN, FETCH_RATE_LIMITED, SEARCH_BACKEND_FAILED, etc.

- **Observability**:
  - Project-owned structured logger (no global logging pollution)
  - Search health reporting with fallback rate, error rate, provider circuit status
  - Live test metrics: success rate, P50/P95 latency, fallback rate, error type breakdown
  - DDG fallback detailed metrics tracking

- **Security**:
  - SSRF protection
  - URL validation
  - Sensitive data filtering
  - robots.txt respect
  - SECURITY.md policy document

### 🔧 Changed
- `web_search` now uses new `SearchService` by default, falls back to old `SearchEngine`
- `search_health` now reports active `SearchService` status instead of old `SearchEngine`
- MCP E2E tests split into deterministic (required CI) and live (scheduled) layers
- Experimental features moved to `extras/` directory for physical isolation
- Documentation auto-generated from MCP tool registry (single source of truth)
- Coverage threshold management with baseline ratchet approach

### 🐛 Fixed
- MCP Live E2E server startup command (was `python -m webscout_mcp.server`, now `python -m webscout_mcp serve`)
- Global `logging.setLoggerClass()` pollution of host Python process
- F821 undefined-name lint exemptions removed
- `cache_clear()` logging TypeError with standard Python logger
- AsyncClient event loop lifecycle issue (recreate client on loop change)
- ConcurrencyLimiter semaphore/event loop deadlock causing 10-minute CI timeout
- Live Test pytest exit code being swallowed by `tee` (added `set -o pipefail`)
- Live Report direct push to protected main branch (now uses artifacts only)
- Circuit breaker half-open failure not resetting recovery timer
- SerpAPI region/locale handling (wt-wt → proper language/country codes)
- MODULE_STATUS.md tool count drift (now auto-generated)

### 📚 Documentation
- README.md with badges, quick start, tool reference, configuration
- MODULE_STATUS.md (auto-generated from tool registry)
- SECURITY.md with vulnerability reporting policy
- CODE_OF_CONDUCT.md
- Issue templates (Bug Report, Feature Request)
- PR template
- CONTRIBUTING.md

## [Unreleased]

### Added
- **Core Infrastructure Optimization**
  - Unified error hierarchy with 30+ specialized error classes
  - Comprehensive security module (SSRF protection, input validation, rate limiting, sensitive data filtering)
  - Async utilities (retry, concurrency limiter, circuit breaker, performance monitoring)
  - Architecture module (event bus, dependency injection, middleware pipeline, command pattern)
  - Health check module (liveness/readiness probes, system monitoring, dependency checks)

- **Core Function Deep Optimization**
  - Search optimizer (concurrent search, smart caching, intelligent ranking, query understanding)
  - Content extractor (multi-algorithm fusion, quality assessment, language detection)
  - RAG optimizer (semantic chunking, context compression, query rewriting)
  - Browser optimizer (instance pooling, human behavior simulation)
  - AI optimizer (prompt engineering, output validation, hallucination detection)

- **Extended Feature Modules**
  - SimHash near-duplicate detection
  - Hybrid search RAG optimization
  - Pydantic configuration models
  - PDF document processing
  - Data cleaning pipeline
  - Competitor analysis
  - Knowledge graph construction
  - Prometheus metrics monitoring
  - Browser fingerprint enhancement
  - REST API server
  - OCR engine
  - Multi-language translator
  - Multi-channel alerting

- **Test System**
  - Integration test framework (8 module interaction test suites)
  - Performance benchmark tests (9 module performance tests with statistics)
  - Enhanced conftest.py with custom markers and fixtures
  - 884+ total test cases (unit + integration + performance)

- **Deployment & Operations**
  - Optimized Dockerfile (multi-stage build, health check, non-root user)
  - Enhanced docker-compose.yml (Redis service, resource limits, security options)
  - Enhanced .dockerignore
  - Health check endpoints for container orchestration

- **Documentation**
  - Comprehensive CHANGELOG.md
  - CONTRIBUTING.md with contribution guidelines
  - docs/ directory with usage guides and best practices
  - Enhanced README.md with detailed documentation

### Changed
- Improved error handling consistency across all modules
- Enhanced security validation for all external inputs
- Optimized performance of core search and extraction operations
- Improved documentation and code comments

### Fixed
- Various bug fixes and stability improvements
- Fixed edge cases in content extraction and parsing
- Improved error recovery and retry logic

## [0.4.0] - 2024-08-28

### Added
- Initial public release
- Web search with multiple backends (Bing, DuckDuckGo)
- Web content fetching and extraction
- Web crawling with concurrency control
- AI content processing (summarization, classification, sentiment analysis)
- Vector store and semantic search
- Headless browser automation
- SEO analysis and broken link checking
- Website monitoring
- Data export (multiple formats)
- RSS feed parsing
- Plugin system
- Configuration management
- Logging system
- Caching system
- Rate limiting
- MCP server support (stdio and SSE transport)

## [0.3.0] - 2024-08-20

### Added
- Enhanced search result ranking
- Improved content extraction algorithms
- Added more AI processing capabilities
- Enhanced vector search performance
- Added browser fingerprinting support
- Improved error handling and retry logic

### Changed
- Refactored core modules for better maintainability
- Improved configuration management
- Enhanced logging and monitoring

### Fixed
- Fixed various bugs in web crawling
- Fixed content extraction edge cases
- Improved stability of headless browser operations

## [0.2.0] - 2024-08-10

### Added
- Added plugin system for extensibility
- Added data export in multiple formats
- Added RSS feed parsing
- Enhanced SEO analysis capabilities
- Added website monitoring features
- Improved documentation

### Changed
- Improved performance of search operations
- Enhanced content extraction quality
- Refactored configuration system

### Fixed
- Fixed memory leaks in long-running crawls
- Fixed race conditions in concurrent operations
- Improved error recovery

## [0.1.0] - 2024-08-01

### Added
- Initial alpha release
- Basic web search functionality
- Basic web content fetching
- Basic web crawling
- Basic AI content processing
- Basic vector store
- Basic headless browser support
- MCP server basic support

---

## Upgrade Guide

### From 0.3.x to 0.4.0

1. **Configuration Changes**
   - New configuration options available for security, rate limiting, and caching
   - Review the updated configuration documentation for new options

2. **API Changes**
   - Error handling has been unified - update error catching code
   - New health check endpoints available
   - Enhanced search and extraction APIs

3. **Dependencies**
   - New optional dependencies for OCR, translation, and API server
   - Install with `pip install webscout-mcp[all]` for all features

4. **Deployment**
   - New Docker image with health check support
   - Updated docker-compose.yml with Redis support
   - Review the deployment documentation for new options

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/):

- **MAJOR** version: Incompatible API changes
- **MINOR** version: New functionality in a backwards-compatible manner
- **PATCH** version: Backwards-compatible bug fixes

---

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
