r"""Compatibility shim for content_quality.

This module has moved to :mod:`webscout_mcp.extras.content_quality`.

Why it moved: content_quality and broken_links are website-analysis helpers,
not part of the core web-research path. REFACTOR_PLAN.md recorded that they
should leave Core for exactly that reason, and MODULE_STATUS.md described them
as Experimental while listing them under "Beta Enhancement Modules" in the
same document - the two tables disagreed.

What did NOT change: the MCP tool \content_quality\ is one of the 11 frozen
tools in COMPATIBILITY.md. It keeps its name, parameter schema and return
structure, and the MCP server still exposes it. Only the Python import path of
the implementation moved.

Deprecated:
    Import from webscout_mcp.extras.content_quality instead.
    This shim will be removed in a future major version.
"""

from __future__ import annotations

import warnings

from .extras.content_quality import (  # noqa: F401
    ContentQualityAnalyzer,
    ContentQualityMetrics,
    analyze_content_quality,
)

__all__ = [
    "ContentQualityAnalyzer",
    "ContentQualityMetrics",
    "analyze_content_quality",
]

warnings.warn(
    "webscout_mcp.content_quality is deprecated, import from webscout_mcp.extras.content_quality instead.",
    DeprecationWarning,
    stacklevel=2,
)
