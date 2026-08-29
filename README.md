# webscout-mcp

[![PyPI version](https://img.shields.io/pypi/v/webscout-mcp.svg)](https://pypi.org/project/webscout-mcp/)
[![Python versions](https://img.shields.io/pypi/pyversions/webscout-mcp.svg)](https://pypi.org/project/webscout-mcp/)
[![Tests](https://github.com/wxs-lang/webscout-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/wxs-lang/webscout-mcp/actions/workflows/tests.yml)
[![Code Quality](https://github.com/wxs-lang/webscout-mcp/actions/workflows/quality.yml/badge.svg)](https://github.com/wxs-lang/webscout-mcp/actions/workflows/quality.yml)
[![Documentation](https://github.com/wxs-lang/webscout-mcp/actions/workflows/docs.yml/badge.svg)](https://wxs-lang.github.io/webscout-mcp/)
[![Docker Pulls](https://img.shields.io/docker/pulls/wxslang/webscout-mcp.svg)](https://hub.docker.com/r/wxslang/webscout-mcp)
[![License](https://img.shields.io/github/license/wxs-lang/webscout-mcp.svg)](https://github.com/wxs-lang/webscout-mcp/blob/main/LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/wxs-lang/webscout-mcp.svg)](https://github.com/wxs-lang/webscout-mcp/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/wxs-lang/webscout-mcp.svg)](https://github.com/wxs-lang/webscout-mcp/network/members)
[![GitHub Issues](https://img.shields.io/github/issues/wxs-lang/webscout-mcp.svg)](https://github.com/wxs-lang/webscout-mcp/issues)
[![Last Commit](https://img.shields.io/github/last-commit/wxs-lang/webscout-mcp.svg)](https://github.com/wxs-lang/webscout-mcp/commits/main)
[![Commit Activity](https://img.shields.io/github/commit-activity/m/wxs-lang/webscout-mcp.svg)](https://github.com/wxs-lang/webscout-mcp/commits/main)

AI-powered web intelligence platform for AI agents. Search, fetch, crawl, extract, understand, and monitor the web — with built-in AI, vector search, browser automation, and alerting. Everything stays on your machine.

[**中文版本简介**](README_zh.md) | 快速了解项目，适合中文用户阅读

## ✨ Features

### 🔍 Core Web Tools
- **Multi-backend search** — Bing, DuckDuckGo, Google, Brave HTML with automatic failover and result merging
- **Smart content extraction** — trafilatura + readability-lxml + html2text fallback, clean article content
- **Concurrent crawler** — BFS crawl with depth/page limits, robots.txt compliance, retry on failures
- **Structured data extraction** — CSS selectors, attributes, regex extraction
- **Metadata extraction** — JSON-LD, OpenGraph, Twitter Cards, article metadata, images, links
- **RSS/Atom support** — parse feeds and feed indexes

### 🤖 AI Content Understanding
- **Text summarization** — automatic article and page summarization
- **Question answering** — ask questions about fetched content
- **Key points extraction** — extract main ideas and takeaways
- **Content classification** — categorize content into custom categories
- **Tag generation** — auto-generate relevant tags
- **Sentiment analysis** — analyze text sentiment
- **Document comparison** — compare two documents side by side
- **Entity extraction** — extract people, places, organizations, dates
- **Multiple LLM backends** — Ollama (local/free), OpenAI, Doubao, custom OpenAI-compatible

### 🧠 Vector Search & RAG
- **Semantic search** — search by meaning, not just keywords
- **RAG (Retrieval-Augmented Generation)** — answer questions based on your crawled content
- **Local vector database** — ChromaDB persistent storage
- **Multiple embedding backends** — local sentence-transformers (free), OpenAI, custom
- **Document chunking** — automatic text splitting with overlap
- **Similarity threshold** — configurable relevance filtering

### 🌐 Headless Browser Automation
- **JavaScript rendering** — fetch modern SPAs and dynamic content
- **User interaction simulation** — scroll, click, fill forms
- **Screenshot capture** — full-page screenshots
- **PDF export** — convert web pages to PDF
- **Login state management** — cookie persistence across sessions
- **Anti-detection stealth mode** — navigator.webdriver, plugins, languages spoofing
- **Resource blocking** — block images, media, CSS, fonts for faster loading
- **Proxy support** — HTTP/HTTPS proxy configuration
- **Multiple browsers** — Chromium, Firefox, WebKit

### 📡 Web Monitoring & Alerting
- **Scheduled monitoring** — configurable check intervals
- **Content change detection** — text, HTML, specific element changes
- **Keyword monitoring** — appearance, disappearance, count changes
- **Price monitoring** — track price changes with threshold alerts
- **Change history** — persistent history with diff generation
- **Multi-channel alerts** — Webhook, Email (SMTP), DingTalk, WeCom
- **Configurable thresholds** — minimum change size, similarity thresholds

### ⚡ Performance & Security
- **Smart caching** — SQLite cache with TTL, size limits, automatic eviction
- **Rate limiting** — per-domain token-bucket rate limiting
- **SSRF protection** — blocks localhost, sensitive ports, invalid schemes
- **Browser fingerprint rotation** — random User-Agents + realistic headers
- **TLS fingerprint simulation** — realistic TLS ClientHello fingerprints
- **Connection pooling** — persistent HTTP connections
- **Cookie management** — automatic cookie handling and persistence

### 🚀 Easy Setup & Deployment
- **One-click setup** — `webscout-mcp setup` auto-installs all dependencies
- **System detection** — auto-detects OS, CPU, memory, GPU
- **Smart recommendations** — suggests optimal configuration based on hardware
- **Docker support** — pre-built images for amd64 and arm64
- **Docker Compose** — one-command deployment
- **systemd service** — Linux service file for production
- **Kubernetes** — deployment manifests for container orchestration
- **Configuration hot-reload** — reload config without restart

### 🔍 Website Analysis & Optimization
- **SEO analyzer** — comprehensive SEO audit: meta tags, headings, images, links, URL structure, content length, Open Graph, Twitter Cards, Schema markup, with multi-dimensional scoring and actionable recommendations
- **Broken link checker** — detect broken links, redirect chains, invalid URLs, mixed content; classify internal/external/mailto/tel/javascript links; detailed reporting with statistics
- **Performance analyzer** — page performance audit: HTML size, DOM size, resource counts, render-blocking resources, inline CSS/JS, optimization techniques (lazy loading, preconnect, preload), compression/cache detection, performance scoring
- **Content quality assessor** — readability scores (Flesch-Kincaid, Gunning Fog, SMOG), keyword density, content structure analysis, duplicate content detection, quality scoring

### 📊 Export & Integration
- **Multiple export formats** — JSON, CSV, Excel, Parquet, SQLite, Markdown, HTML
- **Field selection & ordering** — export only specified fields with custom column order
- **Append mode** — incremental exports for CSV and SQLite
- **MCP server** — native Model Context Protocol support
- **CLI interface** — command-line tools for search, fetch, crawl
- **Python API** — full programmatic access to all features
- **Sitemap support** — parse sitemap.xml and sitemap indexes
- **Incremental crawling** — only re-fetch changed pages via ETag/Last-Modified

## 📦 Installation

### Quick Install
```bash
pip install webscout-mcp
```

Requires Python 3.10+.

### One-Click Full Setup (Recommended)
```bash
# Install core package
pip install webscout-mcp

# Run setup to install all optional dependencies
webscout-mcp setup --playwright --ollama --vector-store
```

The setup command will:
- Detect your system configuration (OS, CPU, memory, GPU)
- Install Playwright and Chromium browser
- Install Ollama and download a local LLM (optional)
- Install ChromaDB and sentence-transformers for vector search (optional)
- Generate a configuration file
- Run a health check to verify everything works

### Optional Dependencies
```bash
# Browser automation (Playwright)
pip install webscout-mcp[browser]
playwright install chromium

# Vector search & RAG (ChromaDB + sentence-transformers)
pip install webscout-mcp[vector]

# AI content understanding (OpenAI client)
pip install webscout-mcp[ai]

# All features
pip install webscout-mcp[all]
```

### Docker
```bash
docker pull wxslang/webscout-mcp:latest
docker run -p 8000:8000 wxslang/webscout-mcp:latest
```

## 🚀 Quick Start

### MCP Client Configuration

Add to your MCP client config:

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):
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

**Cursor** (Settings → MCP → Add new MCP server):
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

### CLI Usage

```bash
# Search the web
webscout-mcp search "python web scraping" --max-results 10

# Fetch a page
webscout-mcp fetch https://example.com --extract --format markdown

# Crawl a site
webscout-mcp crawl https://example.com --depth 2 --pages 50

# Run setup
webscout-mcp setup --playwright

# Start MCP server
webscout-mcp serve
```

### Python API

```python
from webscout_mcp import WebScout

# Initialize
scout = WebScout()

# Search
results = scout.search("AI agents", max_results=5)
for result in results:
    print(result.title, result.url)

# Fetch and extract
page = scout.fetch("https://example.com/article")
print(page.title)
print(page.content)  # Clean article text

# Crawl
pages = scout.crawl("https://example.com", depth=2, max_pages=20)
```

## 🤖 AI Content Understanding

```python
from webscout_mcp.ai_processor import AIProcessor, AIConfig

# Use local Ollama (free, no API key needed)
config = AIConfig(backend="ollama", model="qwen2.5:7b")
ai = AIProcessor(config=config)

# Summarize
summary = ai.summarize(page.content, max_length=500)
print(summary.content)

# Ask questions
answer = ai.answer_question(page.content, "What are the main points?")
print(answer.content)

# Extract key points
points = ai.extract_key_points(page.content, num_points=5)
print(points.content)

# Analyze sentiment
sentiment = ai.analyze_sentiment(page.content)
print(sentiment.content)
```

**Using OpenAI API:**
```python
config = AIConfig(
    backend="openai",
    model="gpt-4o",
    api_key="your-api-key",
)
```

**Using Doubao (豆包):**
```python
config = AIConfig(
    backend="doubao",
    model="ep-20240101",
    api_key="your-api-key",
)
```

## 🧠 Vector Search & RAG

```python
from webscout_mcp.vector_store import VectorStore, RAGEngine, Document

# Initialize vector store (local, free)
store = VectorStore()

# Add documents
doc = Document.from_text(page.content, source=page.url)
store.add_document(doc)

# Semantic search
results = store.search("how to build AI agents", n_results=5)
for result in results:
    print(f"[{result.score:.2f}] {result.document.content[:100]}")

# RAG: Ask questions based on your documents
rag = RAGEngine(vector_store=store)
answer = rag.query("What is the best approach for web scraping?")
print(answer["answer"])
print("Sources:", answer["sources"])
```

## 🌐 Headless Browser Automation

```python
from webscout_mcp.browser_fetcher import BrowserFetcher, BrowserConfig

# Initialize
config = BrowserConfig(headless=True, block_media=True)
browser = BrowserFetcher(config=config)

# Fetch JS-rendered page
result = browser.fetch(
    "https://example.com/spa",
    wait_for_selector=".content",
    scroll_to_bottom=True,
)
print(result.title)
print(result.content)

# Take screenshot
browser.take_screenshot("https://example.com", "screenshot.png", full_page=True)

# Export to PDF
browser.export_pdf("https://example.com", "page.pdf")

# Click element
result = browser.click_element("https://example.com", "button.load-more")

# Fill form
result = browser.fill_form(
    "https://example.com/login",
    {"#username": "user", "#password": "pass"},
    submit_selector="button[type=submit]",
)

browser.close()
```

## 📡 Web Monitoring & Alerting

```python
from webscout_mcp.monitor import WebMonitor, MonitorConfig, WebhookAlert, EmailAlert

# Initialize
config = MonitorConfig(check_interval=300, min_change_size=10)
monitor = WebMonitor(config=config)

# Add alert channels
monitor.add_alert_channel(WebhookAlert("https://hooks.example.com/alert"))
monitor.add_alert_channel(EmailAlert(
    smtp_server="smtp.gmail.com",
    smtp_port=587,
    username="you@gmail.com",
    password="app-password",
    from_addr="you@gmail.com",
    to_addrs=["recipient@example.com"],
))

# Check for changes
changes = monitor.check_url("https://example.com/pricing")
for change in changes:
    print(f"{change.change_type}: {change.old_value} -> {change.new_value}")

# Get history
history = monitor.get_history("https://example.com/pricing")
```

## 🔍 Website Analysis & Optimization

### SEO Analysis
```python
from webscout_mcp.seo_analyzer import SEOAnalyzer

# Initialize
analyzer = SEOAnalyzer()

# Analyze a page
html = "<html>...</html>"
metrics = analyzer.analyze(html, url="https://example.com")

# Check scores
print(f"Overall SEO Score: {metrics.overall_score}/100")
print(f"Meta Score: {metrics.meta_score}")
print(f"Heading Score: {metrics.heading_score}")
print(f"Image Score: {metrics.image_score}")

# Check issues and recommendations
print("Issues:", metrics.issues)
print("Recommendations:", metrics.recommendations)
```

### Broken Link Checking
```python
from webscout_mcp.broken_link_checker import BrokenLinkChecker

# Initialize
checker = BrokenLinkChecker(timeout=10.0, max_redirects=5)

# Check all links on a page
html = "<html>...</html>"
report = checker.check_page(html, base_url="https://example.com")

# Check statistics
print(f"Total links: {report.total_links}")
print(f"OK: {report.ok_links}")
print(f"Broken: {report.broken_links}")
print(f"Redirects: {report.redirect_links}")
print(f"Broken percentage: {report.broken_link_percentage}%")

# Get only broken links
broken = checker.get_broken_links(report)
for link in broken:
    print(f"[{link.status}] {link.url} - {link.error_message}")

# Generate human-readable summary
print(checker.generate_summary(report))
```

### Performance Analysis
```python
from webscout_mcp.performance_analyzer import PerformanceAnalyzer

# Initialize
analyzer = PerformanceAnalyzer()

# Analyze page performance
html = "<html>...</html>"
headers = {"Content-Encoding": "gzip", "Cache-Control": "max-age=3600"}
metrics = analyzer.analyze(html, url="https://example.com", response_headers=headers)

# Check scores
print(f"Overall Performance Score: {metrics.overall_score}/100")
print(f"HTML Size: {metrics.html_size_kb}KB (score: {metrics.html_size_score})")
print(f"DOM Nodes: {metrics.dom_node_count} (score: {metrics.dom_size_score})")
print(f"Requests: {metrics.request_count} (score: {metrics.request_count_score})")

# Check optimization techniques
print(f"Has gzip: {metrics.has_gzip}")
print(f"Has brotli: {metrics.has_brotli}")
print(f"Has lazy loading: {metrics.has_lazy_loading}")
print(f"Has preconnect: {metrics.has_preconnect}")

# Check issues and recommendations
print("Issues:", metrics.issues)
print("Warnings:", metrics.warnings)
print("Recommendations:", metrics.recommendations)
```

### Enhanced Data Export
```python
from webscout_mcp.data_exporter import DataExporter, ExportConfig

# Sample data
data = [
    {"title": "Result 1", "url": "https://example.com/1", "score": 0.95},
    {"title": "Result 2", "url": "https://example.com/2", "score": 0.85},
]

# Export to JSON
config = ExportConfig(format="json", output_path="results.json", pretty_json=True)
exporter = DataExporter(config=config)
result = exporter.export(data)
print(f"Exported {result.record_count} records to {result.output_path}")

# Export to CSV with field selection
config = ExportConfig(
    format="csv",
    output_path="results.csv",
    fields=["title", "url"],  # Only export these fields
    csv_delimiter=",",
)
exporter = DataExporter(config=config)
result = exporter.export(data)

# Export to Excel
config = ExportConfig(format="excel", output_path="results.xlsx", excel_sheet_name="Results")
exporter = DataExporter(config=config)
result = exporter.export(data)

# Export to SQLite
config = ExportConfig(format="sqlite", output_path="results.db", sqlite_table_name="search_results")
exporter = DataExporter(config=config)
result = exporter.export(data)

# Export to Parquet (columnar storage)
config = ExportConfig(format="parquet", output_path="results.parquet")
exporter = DataExporter(config=config)
result = exporter.export(data)

# Export to Markdown
config = ExportConfig(format="markdown", output_path="results.md")
exporter = DataExporter(config=config)
result = exporter.export(data)

# Export to HTML
config = ExportConfig(format="html", output_path="results.html")
exporter = DataExporter(config=config)
result = exporter.export(data)

# Using convenience function
from webscout_mcp.data_exporter import export_data
result = export_data(data, "results.json", export_format="json", fields=["title", "url"])
```

## ⚙️ Configuration

### Environment Variables

```bash
# Core
WEBSCOUT_CACHE_ENABLED=true
WEBSCOUT_CACHE_TTL=3600
WEBSCOUT_RATE_LIMIT_ENABLED=true

# Search
WEBSCOUT_SEARCH_DEFAULT_BACKEND=bing
WEBSCOUT_SEARCH_MAX_RESULTS=10

# AI
WEBSCOUT_AI_BACKEND=ollama
WEBSCOUT_AI_MODEL=qwen2.5:7b
WEBSCOUT_AI_API_KEY=your-key

# Vector Store
WEBSCOUT_VECTOR_DB=chroma
WEBSCOUT_EMBEDDING_BACKEND=local
WEBSCOUT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5

# Browser
WEBSCOUT_BROWSER_TYPE=chromium
WEBSCOUT_BROWSER_HEADLESS=true
WEBSCOUT_BROWSER_BLOCK_MEDIA=true

# Monitor
WEBSCOUT_MONITOR_INTERVAL=300
WEBSCOUT_MONITOR_MIN_CHANGE=10

# Setup
WEBSCOUT_SETUP_PLAYWRIGHT=true
WEBSCOUT_SETUP_OLLAMA=false
WEBSCOUT_SETUP_CHROMADB=false
```

### Config File

Create `~/.config/webscout/config.toml`:
```toml
[server]
host = "127.0.0.1"
port = 8000

[cache]
enabled = true
ttl = 3600

[search]
default_backend = "bing"
max_results = 10

[ai]
backend = "ollama"
model = "qwen2.5:7b"

[vector_store]
enabled = true
vector_db = "chroma"
embedding_backend = "local"

[browser]
enabled = true
headless = true

[monitor]
check_interval = 300
```

## 📚 Documentation

- [README](README.md) — This file
- [Project Introduction](PROJECT_INTRODUCTION.md) — Detailed project overview and architecture
- [Deployment Guide](DEPLOYMENT.md) — Docker, systemd, Kubernetes deployment
- [Examples](examples/) — Usage examples and sample code
- [CHANGELOG](CHANGELOG.md) — Version history
- [CONTRIBUTING](CONTRIBUTING.md) — Contributing guidelines
- [CODE OF CONDUCT](CODE_OF_CONDUCT.md) — Community code of conduct
- [SECURITY](SECURITY.md) — Security policy and vulnerability reporting

## 🧪 Testing

```bash
# Install dev dependencies
pip install webscout-mcp[dev]

# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=webscout_mcp --cov-report=html
```

Test coverage: **395+ tests** covering all modules.

## 🤝 Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- [trafilatura](https://github.com/adbar/trafilatura) — content extraction
- [readability-lxml](https://github.com/buriy/python-readability) — readability fallback
- [Playwright](https://playwright.dev/) — browser automation
- [ChromaDB](https://www.trychroma.com/) — vector database
- [sentence-transformers](https://www.sbert.net/) — text embeddings
- [Ollama](https://ollama.com/) — local LLM runtime
- [httpx](https://www.python-httpx.org/) — HTTP client
- [BeautifulSoup](https://www.crummy.com/software/BeautifulSoup/) — HTML parsing

---

**Built with ❤️ for the AI agent community.**
