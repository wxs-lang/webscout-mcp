#!/usr/bin/env python3
"""Automated documentation generator for webscout-mcp.

This script generates documentation from the actual MCP tool registrations
in server.py, ensuring documentation always stays in sync with code.

Generated files:
- MODULE_STATUS.md - Module stability and MCP integration status
- docs/tools.md - Detailed MCP tool reference
- README.md (tool table section) - Quick tool overview

Usage:
    python scripts/generate_docs.py
    python scripts/generate_docs.py --check  # Only check if docs are up-to-date

CI integration:
    python scripts/generate_docs.py --check
    git diff --exit-code
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ToolParam:
    """A parameter for an MCP tool."""

    name: str
    type: str
    default: str | None = None
    description: str = ""
    required: bool = True


@dataclass
class MCPTool:
    """An MCP tool definition extracted from server.py."""

    name: str
    description: str = ""
    params: list[ToolParam] = field(default_factory=list)
    is_async: bool = False
    stability: str = "✅ Stable"
    category: str = "Other"

    @property
    def required_params(self) -> list[ToolParam]:
        return [p for p in self.params if p.required]

    @property
    def optional_params(self) -> list[ToolParam]:
        return [p for p in self.params if not p.required]


def extract_tools_from_server(server_path: Path) -> list[MCPTool]:
    """Extract MCP tool definitions from server.py using AST parsing.

    This avoids importing the MCP server (which is slow due to mcp library
    import time ~14s) and instead parses the source code directly.
    """
    with open(server_path, "r") as f:
        source = f.read()

    tree = ast.parse(source)
    tools: list[MCPTool] = []

    # Find the create_server function
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "create_server":
            # Look for nested functions with @mcp.tool() decorator
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Check if it has @mcp.tool() decorator
                    has_tool_decorator = False
                    for decorator in inner.decorator_list:
                        if isinstance(decorator, ast.Call):
                            if isinstance(decorator.func, ast.Attribute):
                                if decorator.func.attr == "tool":
                                    has_tool_decorator = True
                                    break

                    if not has_tool_decorator:
                        continue

                    # Extract tool information
                    tool = MCPTool(
                        name=inner.name,
                        is_async=isinstance(inner, ast.AsyncFunctionDef),
                    )

                    # Extract description from docstring
                    if inner.body and isinstance(inner.body[0], ast.Expr):
                        if isinstance(inner.body[0].value, ast.Constant):
                            docstring = inner.body[0].value.value
                            tool.description = docstring.strip().split("\n")[0]

                    # Extract parameters
                    for arg in inner.args.args:
                        if arg.arg == "self":
                            continue

                        param = ToolParam(
                            name=arg.arg,
                            type=ast.unparse(arg.annotation) if arg.annotation else "Any",
                        )

                        # Check for default value
                        if inner.args.defaults:
                            num_defaults = len(inner.args.defaults)
                            num_args = len(inner.args.args)
                            default_start = num_args - num_defaults
                            arg_index = inner.args.args.index(arg)
                            if arg_index >= default_start:
                                default_index = arg_index - default_start
                                default_value = inner.args.defaults[default_index]
                                param.default = ast.unparse(default_value)
                                param.required = False

                        tool.params.append(param)

                    # Categorize tool
                    tool.category = _categorize_tool(tool.name)
                    tool.stability = _get_tool_stability(tool.name)

                    tools.append(tool)

    return tools


def _categorize_tool(name: str) -> str:
    """Categorize a tool by name."""
    if name in ("web_search",):
        return "Search"
    if name in ("web_fetch",):
        return "Fetch"
    if name in ("web_crawl", "web_extract"):
        return "Crawl & Extract"
    if name in ("cache_stats", "cache_clear"):
        return "Cache"
    if name in ("search_health",):
        return "Health"
    if name in ("metadata_extract", "rss_parse", "content_quality", "broken_links"):
        return "Content Analysis"
    return "Other"


def _get_tool_stability(name: str) -> str:
    """Get stability level for a tool."""
    stable_tools = {
        "web_search",
        "web_fetch",
        "web_extract",
        "cache_stats",
        "cache_clear",
    }
    beta_tools = {
        "web_crawl",
        "search_health",
        "metadata_extract",
        "rss_parse",
    }
    if name in stable_tools:
        return "✅ Stable"
    if name in beta_tools:
        return "🔶 Beta"
    return "🧪 Experimental"


def generate_module_status(tools: list[MCPTool]) -> str:
    """Generate MODULE_STATUS.md content."""
    stable_tools = [t for t in tools if t.stability == "✅ Stable"]
    beta_tools = [t for t in tools if t.stability == "🔶 Beta"]
    experimental_tools = [t for t in tools if t.stability == "🧪 Experimental"]

    content = f"""# Module Stability & MCP Integration Status

> **This file is auto-generated by `scripts/generate_docs.py`. Do not edit manually.**
> Last generated: from actual MCP tool registrations in server.py

This document provides transparency about the stability and integration status of each module in webscout-mcp.

## Stability Levels

- **✅ Stable**: Core modules, well-tested, used in production, guaranteed API stability
- **🔶 Beta**: Functional, tested, but may have edge cases; API may change
- **🧪 Experimental**: Code exists, but not thoroughly tested; may have bugs; API will change
- **📦 Library-only**: Available as Python library, but NOT exposed as MCP tools

## MCP Tool Integration Status

### ✅ Currently Exposed as MCP Tools ({len(tools)} tools)

| Tool | Category | Stability | Description |
|------|----------|-----------|-------------|
"""

    for tool in sorted(tools, key=lambda t: (t.category, t.name)):
        desc = tool.description[:80] + "..." if len(tool.description) > 80 else tool.description
        content += f"| `{tool.name}` | {tool.category} | {tool.stability} | {desc} |\n"

    content += f"""
---

## Tool Summary by Category

### 🔍 Search (1 tool)
- `web_search` - Multi-backend web search with fallback

### 📥 Fetch (1 tool)
- `web_fetch` - Fetch and parse web pages

### 🕷️ Crawl & Extract (2 tools)
- `web_crawl` - Concurrent website crawling
- `web_extract` - Structured content extraction

### 💾 Cache (2 tools)
- `cache_stats` - View cache statistics
- `cache_clear` - Clear cache

### 💚 Health (1 tool)
- `search_health` - Search backend health and circuit breaker status

### 📊 Content Analysis (4 tools)
- `metadata_extract` - Extract page metadata (JSON-LD, OpenGraph, Twitter Cards)
- `rss_parse` - Parse RSS/Atom feeds
- `content_quality` - Analyze content quality
- `broken_links` - Check for broken links

---

## Stability Breakdown

| Level | Count | Tools |
|-------|-------|-------|
| ✅ Stable | {len(stable_tools)} | {', '.join(f'`{t.name}`' for t in stable_tools)} |
| 🔶 Beta | {len(beta_tools)} | {', '.join(f'`{t.name}`' for t in beta_tools)} |
| 🧪 Experimental | {len(experimental_tools)} | {', '.join(f'`{t.name}`' for t in experimental_tools) or 'None'} |

---

## Module Classification

### ✅ Stable Core Modules

These modules are the foundation of webscout-mcp. They are well-tested, used in the core MCP tools, and have stable APIs.

| Module | Description | MCP Integrated |
|--------|-------------|----------------|
| `search.py` | Multi-backend search engine | ✅ Yes |
| `fetcher.py` | HTTP fetching with retry | ✅ Yes |
| `crawler.py` | Concurrent web crawler | ✅ Yes |
| `extractor.py` | Content extraction | ✅ Yes |
| `cache.py` | SQLite-based caching | ✅ Yes |
| `config.py` | Configuration management | 📦 Library |
| `errors.py` | Standard error system | 📦 Library |
| `exceptions.py` | Exception hierarchy | 📦 Library |
| `robots.py` | robots.txt compliance | 📦 Library |
| `sitemap.py` | sitemap.xml parsing | 📦 Library |
| `server.py` | MCP server implementation | ✅ Yes |

### 🔶 Beta Enhancement Modules

| Module | Description | MCP Integrated |
|--------|-------------|----------------|
| `metadata_extractor.py` | Page metadata extraction | ✅ Yes |
| `rss_parser.py` | RSS/Atom feed parsing | ✅ Yes |
| `content_quality.py` | Content quality analysis | ✅ Yes |
| `broken_link_checker.py` | Broken link checking | ✅ Yes |
| `search_health.py` | Search health monitoring | ✅ Yes |
| `serpapi_backend.py` | SerpAPI search backend | 📦 Library |

### 🧪 Experimental Modules (Extras)

These modules are available in `webscout_mcp.extras` and are not part of the core MCP tools.

| Module | Description |
|--------|-------------|
| `extras/ai_optimizer.py` | AI-powered query optimization |
| `extras/rag_optimizer.py` | RAG pipeline optimization |
| `extras/knowledge_graph.py` | Knowledge graph construction |
| `extras/competitor_analyzer.py` | Competitor analysis |
| `extras/performance_analyzer.py` | Performance analysis |
| `extras/monitor.py` | Monitoring and alerting |
| `extras/seo_analyzer.py` | SEO analysis |

---

## How to Regenerate This Document

```bash
python scripts/generate_docs.py
```

This will regenerate this file from the actual tool registrations in server.py.
"""
    return content


def generate_tools_doc(tools: list[MCPTool]) -> str:
    """Generate docs/tools.md content."""
    content = f"""# MCP Tools Reference

> **This file is auto-generated by `scripts/generate_docs.py`. Do not edit manually.**

Complete reference for all {len(tools)} MCP tools exposed by webscout-mcp.

---

## Table of Contents

"""

    # Generate TOC by category
    categories = {}
    for tool in tools:
        categories.setdefault(tool.category, []).append(tool)

    for category, category_tools in categories.items():
        content += f"### {category}\n\n"
        for tool in category_tools:
            content += f"- [`{tool.name}`](#{tool.name})\n"
        content += "\n"

    content += "---\n\n"

    # Generate detailed tool documentation
    for category, category_tools in categories.items():
        content += f"## {category}\n\n"
        for tool in category_tools:
            content += f"### `{tool.name}`\n\n"
            content += f"**Stability**: {tool.stability}  \n"
            content += f"**Async**: {'Yes' if tool.is_async else 'No'}  \n\n"
            content += f"{tool.description}\n\n"

            if tool.params:
                content += "**Parameters:**\n\n"
                content += "| Name | Type | Required | Default | Description |\n"
                content += "|------|------|----------|---------|-------------|\n"
                for param in tool.params:
                    required = "Yes" if param.required else "No"
                    default = param.default or "-"
                    content += f"| `{param.name}` | {param.type} | {required} | {default} | |\n"
                content += "\n"

            content += "**Example:**\n\n"
            content += "```json\n"
            example_args = {}
            for param in tool.required_params:
                example_args[param.name] = f"<{param.name}>"
            content += f'{{\n  "name": "{tool.name}",\n  "arguments": {json.dumps(example_args, indent=2)}\n}}\n'
            content += "```\n\n"
            content += "---\n\n"

    return content


def generate_readme_tool_table(tools: list[MCPTool]) -> str:
    """Generate the tool table section for README.md."""
    content = "## Available MCP Tools\n\n"
    content += f"webscout-mcp exposes **{len(tools)} tools** for AI agents:\n\n"
    content += "| Tool | Description | Stability |\n"
    content += "|------|-------------|----------|\n"

    for tool in sorted(tools, key=lambda t: t.name):
        desc = tool.description[:60] + "..." if len(tool.description) > 60 else tool.description
        content += f"| `{tool.name}` | {desc} | {tool.stability} |\n"

    content += "\n"
    return content


def main() -> int:
    """Main entry point for documentation generation."""
    parser = argparse.ArgumentParser(description="Generate webscout-mcp documentation")
    parser.add_argument("--check", action="store_true", help="Only check if docs are up-to-date")
    parser.add_argument("--server-path", type=Path, default=Path("webscout_mcp/server.py"))
    parser.add_argument("--output-dir", type=Path, default=Path("."))
    args = parser.parse_args()

    # Extract tools from server.py
    tools = extract_tools_from_server(args.server_path)
    print(f"Extracted {len(tools)} MCP tools from {args.server_path}")
    for tool in tools:
        print(f"  - {tool.name} ({tool.category}, {tool.stability})")

    if args.check:
        # Check mode: compare generated content with existing files
        print("\nChecking if documentation is up-to-date...")
        checks_passed = True

        # Check MODULE_STATUS.md
        module_status_path = args.output_dir / "MODULE_STATUS.md"
        if module_status_path.exists():
            existing = module_status_path.read_text()
            generated = generate_module_status(tools)
            if existing.strip() != generated.strip():
                print("  ❌ MODULE_STATUS.md is out of date")
                checks_passed = False
            else:
                print("  ✅ MODULE_STATUS.md is up to date")

        # Check docs/tools.md
        tools_doc_path = args.output_dir / "docs" / "tools.md"
        if tools_doc_path.exists():
            existing = tools_doc_path.read_text()
            generated = generate_tools_doc(tools)
            if existing.strip() != generated.strip():
                print("  ❌ docs/tools.md is out of date")
                checks_passed = False
            else:
                print("  ✅ docs/tools.md is up to date")

        if not checks_passed:
            print("\n❌ Documentation is out of date. Run 'python scripts/generate_docs.py' to update.")
            return 1
        print("\n✅ All documentation is up-to-date!")
        return 0

    # Generate mode: write files
    print("\nGenerating documentation...")

    # Generate MODULE_STATUS.md
    module_status_path = args.output_dir / "MODULE_STATUS.md"
    module_status_content = generate_module_status(tools)
    module_status_path.write_text(module_status_content)
    print(f"  ✅ Generated {module_status_path}")

    # Generate docs/tools.md
    tools_doc_path = args.output_dir / "docs" / "tools.md"
    tools_doc_path.parent.mkdir(parents=True, exist_ok=True)
    tools_doc_content = generate_tools_doc(tools)
    tools_doc_path.write_text(tools_doc_content)
    print(f"  ✅ Generated {tools_doc_path}")

    print(f"\n✅ Generated documentation for {len(tools)} MCP tools!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
