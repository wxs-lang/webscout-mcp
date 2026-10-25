"""Compatibility shim for the config module.

This module has moved to webscout_mcp.core.config.

Deprecated:
    Import from webscout_mcp.core.config instead.
    This shim will be removed in a future major version.
"""

from __future__ import annotations

import warnings

from .core.config import *  # noqa: F401,F403

warnings.warn(
    "webscout_mcp.config is deprecated, import from webscout_mcp.core.config instead.",
    DeprecationWarning,
    stacklevel=2,
)
