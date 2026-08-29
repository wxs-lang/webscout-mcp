# Module Stability & MCP Integration Status

This document provides transparency about the stability and integration status of each module in webscout-mcp.

## Stability Levels

- **✅ Stable**: Core modules, well-tested, used in production, guaranteed API stability
- **🔶 Beta**: Functional, tested, but may have edge cases; API may change
- **🧪 Experimental**: Code exists, but not thoroughly tested; may have bugs; API will change
- **📦 Library-only**: Available as Python library, but NOT exposed as MCP tools

## MCP Tool Integration Status

### ✅ Currently Exposed as MCP Tools (6 tools)

| Tool | Module | Stability | Description |
|------|--------|-----------|-------------|
| `web_search` | search.py, search_optimizer.py | ✅ Stable | Multi-backend web search |
| `web_fetch` | fetcher.py | ✅ Stable | Fetch and parse web pages |
| `web_crawl` | crawler.py | 🔶 Beta | Concurrent website crawling |
| `web_extract` | extractor.py, content_extractor.py | ✅ Stable | Structured content extraction |
| `cache_stats` | cache.py | ✅ Stable | View cache statistics |
| `cache_clear` | cache.py | ✅ Stable | Clear cache |

---

## Module Classification

### ✅ Stable Core Modules (14)

These modules are the foundation of webscout-mcp. They are well-tested, used in the core MCP tools, and have stable APIs.

| Module | Description | MCP Integrated |
|--------|-------------|----------------|
| `search.py` | Multi-backend search engine | ✅ Yes |
| `fetcher.py` | HTTP fetching with retry | ✅ Yes |
| `crawler.py` | Concurrent web crawler | ✅ Yes |
| `extractor.py` | Content extraction | ✅ Yes |
| `content_extractor.py` | Advanced content extraction | ✅ Yes |
| `cache.py` | SQLite-based caching | ✅ Yes |
| `config.py` | Configuration management | 📦 Library |
| `errors.py` | Error definitions | 📦 Library |
| `exceptions.py` | Exception hierarchy | 📦 Library |
| `utils.py` | Utility functions | 📦 Library |
| `robots.py` | robots.txt compliance | 📦 Library |
| `sitemap.py` | sitemap.xml parsing | 📦 Library |
| `user_agent.py` | User-Agent rotation | 📦 Library |
| `server.py` | MCP server implementation | ✅ Yes |

### 🔶 Beta Enhancement Modules (20)

These modules are functional and tested, but may have edge cases. They extend the core functionality but are not yet exposed as MCP tools.

| Module | Description | MCP Integrated |
|--------|-------------|----------------|
| `search_optimizer.py` | Search result optimization & ranking | ✅ Yes (via web_search) |
| `hybrid_search.py` | Hybrid search (keyword + semantic) | 📦 Library |
| `metadata_extractor.py` | Metadata extraction (JSON-LD, OG, etc.) | 📦 Library |
| `rss_parser.py` | RSS/Atom feed parsing | 📦 Library |
| `incremental.py` | Incremental crawling (ETag/Last-Modified) | 📦 Library |
| `data_exporter.py` | Multi-format data export (JSON, CSV, Excel, etc.) | 📦 Library |
| `exporter.py` | Basic export functionality | 📦 Library |
| `security.py` | SSRF protection & output filtering | 📦 Library |
| `health.py` | Health checking & system monitoring | 📦 Library |
| `metrics.py` | Performance metrics collection | 📦 Library |
| `async_utils.py` | Async utilities (concurrency, rate limiting) | 📦 Library |
| `architecture.py` | DI container & event bus | 📦 Library |
| `plugin_system.py` | Plugin system framework | 📦 Library |
| `builtin_plugins.py` | Built-in plugins | 📦 Library |
| `config_models.py` | Pydantic configuration models | 📦 Library |
| `logging_config.py` | Structured logging configuration | 📦 Library |
| `setup.py` | One-click setup wizard | 📦 Library |
| `tls_fetcher.py` | TLS fingerprint simulation | 📦 Library |
| `browser_fingerprint.py` | Browser fingerprint generation | 📦 Library |
| `simhash.py` | Similarity hashing for deduplication | 📦 Library |

### 🧪 Experimental Modules (21)

These modules exist in the codebase but have not been thoroughly tested in real-world scenarios. They may have bugs, incomplete implementations, or changing APIs. Use with caution.

| Module | Description | MCP Integrated |
|--------|-------------|----------------|
| `ai_processor.py` | AI content understanding (summarization, QA, etc.) | 📦 Library |
| `ai_optimizer.py` | AI prompt optimization | 📦 Library |
| `vector_store.py` | Vector database integration (ChromaDB) | 📦 Library |
| `rag_optimizer.py` | RAG (Retrieval-Augmented Generation) | 📦 Library |
| `knowledge_graph.py` | Knowledge graph construction | 📦 Library |
| `browser_fetcher.py` | Headless browser automation (Playwright) | 📦 Library |
| `browser_optimizer.py` | Browser optimization & anti-detection | 📦 Library |
| `monitor.py` | Web monitoring & change detection | 📦 Library |
| `alert_channels.py` | Alert channels (Webhook, Email, DingTalk, WeCom) | 📦 Library |
| `seo_analyzer.py` | SEO analysis & auditing | 📦 Library |
| `broken_link_checker.py` | Broken link checking | 📦 Library |
| `performance_analyzer.py` | Web performance analysis | 📦 Library |
| `content_quality.py` | Content quality assessment | 📦 Library |
| `competitor_analyzer.py` | Competitor analysis | 📦 Library |
| `translator.py` | Content translation | 📦 Library |
| `ocr_engine.py` | OCR (Optical Character Recognition) | 📦 Library |
| `pdf_processor.py` | PDF processing & extraction | 📦 Library |
| `data_cleaner.py` | Data cleaning & normalization | 📦 Library |
| `api_server.py` | REST API server (FastAPI) | 📦 Library |

---

## Roadmap: Planned MCP Integration

The following modules are planned for MCP integration in future releases:

### Near-term (Next 1-2 releases)
- [ ] `metadata_extractor.py` - Extract page metadata as MCP tool
- [ ] `rss_parser.py` - RSS feed parsing as MCP tool
- [ ] `data_exporter.py` - Export search results to various formats
- [ ] `security.py` - URL safety checking as MCP tool

### Medium-term (Next 2-4 releases)
- [ ] `browser_fetcher.py` - JavaScript rendering as MCP tool
- [ ] `ai_processor.py` - AI content understanding as MCP tool
- [ ] `monitor.py` - Web monitoring as MCP tool
- [ ] `seo_analyzer.py` - SEO analysis as MCP tool

### Long-term (Future)
- [ ] `vector_store.py` - Vector search as MCP tool
- [ ] `rag_optimizer.py` - RAG as MCP tool
- [ ] `knowledge_graph.py` - Knowledge graph as MCP tool
- [ ] `ocr_engine.py` - OCR as MCP tool
- [ ] `pdf_processor.py` - PDF processing as MCP tool

---

## Test Coverage by Stability Level

| Stability Level | Modules | Avg Test Coverage |
|-----------------|---------|-------------------|
| ✅ Stable | 14 | ~85% |
| 🔶 Beta | 20 | ~60% |
| 🧪 Experimental | 21 | ~30% |

---

## Contributing Guidelines

When contributing to webscout-mcp:

1. **Stable modules**: Changes require extensive testing and may require deprecation warnings
2. **Beta modules**: Changes should include tests, but API changes are acceptable
3. **Experimental modules**: Rapid iteration is encouraged, but please document changes

---

**Last updated**: August 2026
**Total modules**: 55
**MCP tools exposed**: 6
**Stable modules**: 14
**Beta modules**: 20
**Experimental modules**: 21
