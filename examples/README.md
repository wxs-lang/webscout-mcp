# Examples

This directory contains usage examples for webscout-mcp.

## Python API Examples

### basic_usage.py

Demonstrates the core functionality:
- Fetching a web page and extracting content
- Searching the web (basic and multi-backend merged)
- Extracting structured data from a page

```bash
python examples/basic_usage.py
```

### crawler_examples.py

Demonstrates the crawler functionality:
- Basic website crawling
- Reliable crawling with delay and retries
- Exporting crawl results to JSON/CSV/Markdown
- Crawler configuration options

```bash
python examples/crawler_examples.py
```

## Configuration Examples

### mcp_config.json

MCP server configuration examples for different clients and use cases:
- Basic configuration (works with Claude Desktop, Cursor, Codex, etc.)
- Custom configuration with environment variables
- Configuration with HTTP/HTTPS proxy
- SSE transport for remote clients

Copy the relevant section to your MCP client configuration file.

**Client config locations:**
- Claude Desktop (macOS): `~/Library/Application Support/Claude/claude_desktop_config.json`
- Claude Desktop (Windows): `%APPDATA%\Claude\claude_desktop_config.json`
- Claude Desktop (Linux): `~/.config/Claude/claude_desktop_config.json`
- Cursor: Settings → MCP → Add new MCP server
- Codex: `~/.codex/config.json`

## Available Tools

| Tool | Description |
|---|---|
| `web_search` | Search the web via Bing with automatic DuckDuckGo HTML fallback |
| `web_fetch` | Fetch a page and extract the main article (markdown/text/html) |
| `web_crawl` | Concurrent BFS crawl with depth/page limits, respects robots.txt |
| `web_extract` | Pull structured data with CSS selectors, attributes, regex |
| `cache_stats` | Inspect the local cache |
| `cache_clear` | Wipe the cache |

## See Also

- [README.md](../README.md) - Main documentation
- [CONTRIBUTING.md](../CONTRIBUTING.md) - Contribution guidelines
- [CHANGELOG.md](../CHANGELOG.md) - Version history
