r"""Compatibility shim for broken_link_checker.

This module has moved to :mod:`webscout_mcp.extras.broken_link_checker`.

Why it moved: broken link checking is a website-audit helper, not part of the
core web-research path. REFACTOR_PLAN.md recorded that it should leave Core for
that reason.

What did NOT change: the MCP tool `broken_links` is one of the 11 frozen
tools in COMPATIBILITY.md. It keeps its name, parameter schema and return
structure, and the MCP server still exposes it. Only the Python import path of
the implementation moved.

Deprecated:
    Import from webscout_mcp.extras.broken_link_checker instead.
    This shim will be removed in a future major version.
"""

from __future__ import annotations

import warnings

from .extras.broken_link_checker import (  # noqa: F401
    BrokenLinkChecker,
    BrokenLinkReport,
    LinkCheckResult,
    check_broken_links,
)
from .url_safety import check_url_safe  # noqa: F401

# Re-exported so code that patches the old path keeps working:
#     patch("webscout_mcp.broken_link_checker.check_url_safe")
# Patching here does NOT affect the implementation, which resolves the name in
# webscout_mcp.extras.broken_link_checker. New code should patch that module.

__all__ = [
    "BrokenLinkChecker",
    "BrokenLinkReport",
    "LinkCheckResult",
    "check_broken_links",
]

warnings.warn(
    "webscout_mcp.broken_link_checker is deprecated, import from webscout_mcp.extras.broken_link_checker instead.",
    DeprecationWarning,
    stacklevel=2,
)
