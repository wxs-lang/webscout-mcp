"""Compatibility shim for competitor_analyzer module.

This module has been moved to webscout_mcp.extras.competitor_analyzer.
This file provides backward compatibility for existing imports.

Deprecated:
    Import from webscout_mcp.extras.competitor_analyzer instead.
    This compatibility shim will be removed in a future version.
"""

from __future__ import annotations

import warnings

from .extras.competitor_analyzer import *  # noqa: F401,F403
from .extras.competitor_analyzer import (
    ComparisonResult,
    CompetitorAnalyzer,
    SiteMetrics,
    compare_sites,
)

warnings.warn(
    "webscout_mcp.competitor_analyzer is deprecated, import from webscout_mcp.extras.competitor_analyzer instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "SiteMetrics",
    "ComparisonResult",
    "CompetitorAnalyzer",
    "compare_sites",
]
