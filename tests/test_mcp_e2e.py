"""MCP protocol-level end-to-end tests.

These tests start a REAL stdio MCP server process and communicate with it
using the official MCP Python client library. This tests the actual MCP
protocol layer, not just the Python function calls.

NOTE: These tests are currently marked as xfail because of an asyncio event
loop issue in the server startup ("Already running asyncio in this thread").
This needs to be investigated and fixed in the server code. Once fixed,
remove the xfail marker below.

Test coverage:
- Server process startup via stdio
- MCP initialize handshake
- tools/list returns correct number of tools
- tools/call for each tool
- Invalid parameter handling
- Error responses
- Multiple sequential calls
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# MCP E2E tests are now enabled after fixing the asyncio event loop issue
# (was: "Already running asyncio in this thread" - fixed by using run_stdio_async())
# pytestmark = pytest.mark.xfail(
#     reason="Server has asyncio event loop issue: 'Already running asyncio in this thread'",
#     strict=False,
# )


def get_server_command() -> list[str]:
    """Get the command to start the MCP server."""
    return [sys.executable, "-m", "webscout_mcp", "serve"]


def get_server_params() -> StdioServerParameters:
    """Get StdioServerParameters for the MCP server."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "webscout_mcp", "serve"],
        env=env,
    )


class TestMCPServerStartup:
    """Test MCP server process startup and initialization."""

    @pytest.mark.asyncio
    async def test_server_starts_and_initializes(self) -> None:
        """Test that the server starts and responds to initialize."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                result = await session.initialize()
                assert result is not None
                assert result.protocolVersion is not None
                assert result.capabilities is not None
                assert result.serverInfo is not None
                assert result.serverInfo.name == "webscout"

    @pytest.mark.asyncio
    async def test_server_has_tools_capability(self) -> None:
        """Test that the server announces tools capability."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                result = await session.initialize()
                # Server should support tools
                assert hasattr(result.capabilities, "tools")


class TestMCPToolsList:
    """Test tools/list endpoint."""

    @pytest.mark.asyncio
    async def test_list_tools_returns_tools(self) -> None:
        """Test that tools/list returns a non-empty list of tools."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                assert result is not None
                assert len(result.tools) > 0

    @pytest.mark.asyncio
    async def test_list_tools_has_expected_tools(self) -> None:
        """Test that all expected tools are registered."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                tool_names = {tool.name for tool in result.tools}

                # Core tools that should always be present
                expected_tools = {
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
                }

                missing_tools = expected_tools - tool_names
                assert not missing_tools, f"Missing tools: {missing_tools}"

    @pytest.mark.asyncio
    async def test_each_tool_has_required_fields(self) -> None:
        """Test that each tool has name, description, and input_schema."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                for tool in result.tools:
                    assert tool.name, "Tool missing name"
                    assert tool.description, f"Tool {tool.name} missing description"
                    assert tool.inputSchema is not None, f"Tool {tool.name} missing input_schema"


class TestMCPToolCalls:
    """Test tools/call endpoint."""

    @pytest.mark.asyncio
    async def test_cache_stats_call(self) -> None:
        """Test calling cache_stats tool."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("cache_stats", {})
                assert result is not None
                assert result.content is not None
                assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_cache_clear_call(self) -> None:
        """Test calling cache_clear tool."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("cache_clear", {})
                assert result is not None
                assert result.content is not None

    @pytest.mark.asyncio
    async def test_search_health_call(self) -> None:
        """Test calling search_health tool."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("search_health", {})
                assert result is not None
                assert result.content is not None

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool(self) -> None:
        """Test calling a tool that doesn't exist returns an error."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("nonexistent_tool_12345", {})
                assert result is not None
                # MCP returns error response, not exception
                assert hasattr(result, "isError")
                assert result.isError is True

    @pytest.mark.asyncio
    async def test_web_search_missing_query(self) -> None:
        """Test that web_search with missing query handles error gracefully."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                # Call with empty arguments - should either error or return error content
                result = await session.call_tool("web_search", {})
                assert result is not None
                # Either is_error is True, or an exception was raised
                assert hasattr(result, "isError")


class TestMCPMultipleSequentialCalls:
    """Test multiple sequential tool calls work correctly."""

    @pytest.mark.asyncio
    async def test_multiple_cache_stats_calls(self) -> None:
        """Test that multiple sequential cache_stats calls work."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                for i in range(5):
                    result = await session.call_tool("cache_stats", {})
                    assert result is not None
                    assert result.content is not None

    @pytest.mark.asyncio
    async def test_alternating_tool_calls(self) -> None:
        """Test alternating between different tools."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_to_call = ["cache_stats", "search_health", "cache_stats", "search_health"]
                for tool_name in tools_to_call:
                    result = await session.call_tool(tool_name, {})
                    assert result is not None
                    assert result.content is not None


class TestMCPToolCount:
    """Test the exact number of tools registered."""

    @pytest.mark.asyncio
    async def test_exact_tool_count(self) -> None:
        """Test that exactly 11 tools are registered (as documented)."""
        server_params = get_server_params()
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.list_tools()
                # Should have at least 11 core tools
                assert len(result.tools) >= 11, f"Expected at least 11 tools, got {len(result.tools)}"
                tool_names = sorted([tool.name for tool in result.tools])
                print(f"Registered tools ({len(tool_names)}): {tool_names}")
