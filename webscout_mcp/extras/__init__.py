"""Experimental and optional features for webscout-mcp.

This package contains modules that are still in experimental stage,
have limited testing, or are optional features that not all users need.

These modules are available but may change API or be removed in future versions.
For stable core functionality, use the main webscout_mcp package directly.

Usage:
    from webscout_mcp.extras import knowledge_graph
    from webscout_mcp.extras.knowledge_graph import KnowledgeGraph

Or import directly from the main package (compatibility shims are provided):
    from webscout_mcp.knowledge_graph import KnowledgeGraph  # still works
"""

from __future__ import annotations

__all__ = [
    # Website-analysis helpers, moved out of Core (REFACTOR_PLAN.md: they are
    # not part of the web-research path). The MCP tools of the same name stay
    # frozen and keep working; only the implementation import path moved.
    "content_quality",
    "broken_link_checker",
]
