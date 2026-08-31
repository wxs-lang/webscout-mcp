"""
Live MCP E2E tests with REAL network access.

These tests start a real stdio MCP server and call web_search/web_fetch
against REAL search engines and websites. They verify that the full
MCP product path works with real network resources.

IMPORTANT: These tests are NOT part of required CI. They run on a
schedule and can be triggered manually. External network instability
(Bing rate limiting, website downtime) should NOT block PR merges.

For deterministic required CI, see test_mcp_e2e.py which tests the
MCP protocol layer without real network access.
"""

from __future__ import annotations

import os
import sys

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def get_server_params() -> StdioServerParameters:
    """Get server parameters for the MCP server."""
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "webscout_mcp.server"],
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


class TestMCPLiveSearch:
    """Live MCP E2E tests for web_search with real search engines."""

    @pytest.mark.asyncio
    async def test_web_search_real_call(self) -> None:
        """Test that web_search with a real query returns actual results.

        This is a live test: it calls the real MCP server which makes
        real HTTP requests to search engines. Results may vary based
        on network conditions and search engine availability.
        """
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    "web_search",
                    {"query": "python asyncio documentation", "max_results": 3},
                )
                assert result is not None
                assert hasattr(result, "content")
                assert result.content is not None
                assert isinstance(result.content, list)
                assert len(result.content) > 0
                first_block = result.content[0]
                assert hasattr(first_block, "text")
                assert len(first_block.text) > 50
                if hasattr(result, "is_error"):
                    assert not result.is_error, f"web_search returned error: {first_block.text[:200]}"


class TestMCPLiveFetch:
    """Live MCP E2E tests for web_fetch with real websites."""

    @pytest.mark.asyncio
    async def test_web_fetch_real_call(self) -> None:
        """Test that web_fetch with a real URL returns actual content.

        This is a live test: it calls the real MCP server which makes
        real HTTP requests to the target website. Results may vary based
        on network conditions and website availability.
        """
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    "web_fetch",
                    {"url": "https://docs.python.org/3/library/asyncio.html", "extract": True},
                )
                assert result is not None
                assert hasattr(result, "content")
                assert result.content is not None
                assert isinstance(result.content, list)
                assert len(result.content) > 0
                first_block = result.content[0]
                assert hasattr(first_block, "text")
                assert len(first_block.text) > 100
                if hasattr(result, "is_error"):
                    assert not result.is_error, f"web_fetch returned error: {first_block.text[:200]}"
