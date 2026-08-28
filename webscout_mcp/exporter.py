"""Export utilities for search results, fetch results, and crawl results.

Supports JSON, CSV, and Markdown output formats.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict
from typing import Any, Iterable

from .crawler import CrawlResult
from .fetcher import FetchResult
from .search import SearchResult


class Exporter:
    """Export webscout results to various formats."""

    @staticmethod
    def search_to_json(results: list[SearchResult], indent: int = 2) -> str:
        return json.dumps([asdict(r) for r in results], indent=indent, ensure_ascii=False)

    @staticmethod
    def search_to_csv(results: list[SearchResult]) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["position", "title", "url", "snippet", "backend"])
        writer.writeheader()
        for r in results:
            writer.writerow({"position": r.position, "title": r.title, "url": r.url, "snippet": r.snippet, "backend": r.backend})
        return output.getvalue()

    @staticmethod
    def search_to_markdown(results: list[SearchResult], title: str = "Search Results") -> str:
        lines = [f"# {title}\n"]
        for r in results:
            lines.append(f"## {r.position}. [{r.title}]({r.url})")
            if r.backend:
                lines.append(f"*Source: {r.backend}*")
            if r.snippet:
                lines.append(f"\n{r.snippet}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def fetch_to_json(result: FetchResult, indent: int = 2) -> str:
        return json.dumps(result.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def fetch_to_markdown(result: FetchResult) -> str:
        lines = [f"# {result.title or result.url}\n"]
        lines.append(f"**URL:** {result.final_url}")
        lines.append(f"**Status:** {result.status_code}")
        if result.content_type:
            lines.append(f"**Content-Type:** {result.content_type}")
        lines.append("")
        if result.content:
            lines.append("## Content\n")
            lines.append(result.content)
        return "\n".join(lines)

    @staticmethod
    def crawl_to_json(result: CrawlResult, indent: int = 2) -> str:
        return json.dumps(result.to_dict(), indent=indent, ensure_ascii=False)

    @staticmethod
    def crawl_to_csv(result: CrawlResult) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["url", "final_url", "status_code", "title", "content_type", "error"])
        writer.writeheader()
        for page in result.pages:
            writer.writerow({"url": page.url, "final_url": page.final_url, "status_code": page.status_code, "title": page.title, "content_type": page.content_type, "error": page.error or ""})
        return output.getvalue()

    @staticmethod
    def crawl_to_markdown(result: CrawlResult, title: str = "Crawl Results") -> str:
        lines = [f"# {title}\n"]
        lines.append(f"**Seed URL:** {result.seed_url}")
        lines.append(f"**Pages crawled:** {result.pages_crawled}")
        lines.append(f"**Links found:** {result.links_found}")
        lines.append(f"**Skipped (robots.txt):** {result.skipped_robots}")
        lines.append(f"**Errors:** {len(result.errors)}")
        lines.append("")
        if result.pages:
            lines.append("## Pages\n")
            for i, page in enumerate(result.pages, 1):
                lines.append(f"### {i}. [{page.title or page.url}]({page.final_url})")
                lines.append(f"- **Status:** {page.status_code}")
                if page.error:
                    lines.append(f"- **Error:** {page.error}")
                lines.append("")
        return "\n".join(lines)

    @staticmethod
    def save(content: str, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
