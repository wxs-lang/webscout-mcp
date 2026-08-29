"""Compatibility shim for performance_analyzer module.

This module has been moved to webscout_mcp.extras.performance_analyzer.
This file provides backward compatibility for existing imports.

Deprecated:
    Import from webscout_mcp.extras.performance_analyzer instead.
    This compatibility shim will be removed in a future version.
"""

from __future__ import annotations

import warnings

from .extras.performance_analyzer import *  # noqa: F401,F403
from .extras.performance_analyzer import (
    PerformanceAnalyzer,
    PerformanceMetrics,
    analyze_performance,
)

warnings.warn(
    "webscout_mcp.performance_analyzer is deprecated, import from webscout_mcp.extras.performance_analyzer instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "PerformanceMetrics",
    "PerformanceAnalyzer",
    "analyze_performance",
]
