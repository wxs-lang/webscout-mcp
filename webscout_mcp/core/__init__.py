"""Core infrastructure layer.

Contains the primitives every other layer builds on:

    errors    standard error taxonomy (50+ exception types)
    utils     general helpers (URL normalisation, token bucket, truncation)
    cache     SQLite-backed response cache
    config    environment-driven configuration

None of these import from a higher layer. That is what makes the layering real
rather than a folder structure: a module here cannot reach upward, so a change
in core cannot depend on how the MCP server or a provider behaves.

Import compatibility: every module is still reachable from its historical flat
path (`webscout_mcp.errors`, `webscout_mcp.config`, ...) through a
deprecation shim, so this reorganisation cannot break existing callers.
"""

from __future__ import annotations

__all__ = ["cache", "config", "errors", "utils"]
