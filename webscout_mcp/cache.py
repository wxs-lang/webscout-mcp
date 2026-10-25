"""Compatibility shim for the cache module.

This module has moved to webscout_mcp.core.cache.

Deprecated:
    Import from webscout_mcp.core.cache instead.
    This shim will be removed in a future major version.
"""

from __future__ import annotations

import warnings

from .core.cache import *  # noqa: F401,F403

warnings.warn(
    "webscout_mcp.cache is deprecated, import from webscout_mcp.core.cache instead.",
    DeprecationWarning,
    stacklevel=2,
)
