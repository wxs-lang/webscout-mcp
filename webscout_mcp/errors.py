"""Compatibility shim for the core error taxonomy.

This module has moved to webscout_mcp.core.errors.

Part of the five-layer reorganisation described in REFACTOR_PLAN.md: the error
taxonomy is infrastructure that every layer above depends on, so it belongs in
core/ rather than at the package root.

The re-export is a star import rather than an explicit list because the module
defines 50+ exception classes and helper functions, and an explicit list would
silently omit any added later.

Deprecated:
    Import from webscout_mcp.core.errors instead.
    This shim will be removed in a future major version.
"""

from __future__ import annotations

import warnings

from .core.errors import *  # noqa: F401,F403

warnings.warn(
    "webscout_mcp.errors is deprecated, import from webscout_mcp.core.errors instead.",
    DeprecationWarning,
    stacklevel=2,
)
