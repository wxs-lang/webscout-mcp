"""Backward-compatibility tests for v1.3.0 Phase 1.

Phase 1 must not change the external MCP surface. These tests pin that.
"""

from __future__ import annotations

import asyncio

from webscout_mcp.server import Config, create_server


def test_mcp_tool_count_unchanged():
    tools = asyncio.run(create_server(Config()).list_tools())
    names = sorted(t.name for t in tools)
    expected = sorted(
        [
            "web_search",
            "web_fetch",
            "web_crawl",
            "web_extract",
            "cache_stats",
            "cache_clear",
            "search_health",
            "metadata_extract",
            "rss_parse",
            "content_quality",
            "broken_links",
        ]
    )
    assert names == expected, names


def test_observability_still_callable():
    """v1.2.4 observability API must keep working."""
    from webscout_mcp.observability import (
        get_observability_summary,
        record_fetch_attempt,
        reset_for_tests,
    )

    reset_for_tests()
    record_fetch_attempt("fast-http", result="success", latency_ms=1.0)
    s = get_observability_summary()
    assert s["backends"]["fast-http"]["calls"] == 1


def test_ssrf_guard_still_blocks_localhost():
    from webscout_mcp.url_safety import check_url_safe

    assert not check_url_safe("http://127.0.0.1/").safe
    assert not check_url_safe("http://169.254.169.254/latest/meta-data/").safe
    assert check_url_safe("https://example.com/").safe
