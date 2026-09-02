# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
