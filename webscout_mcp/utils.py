"""Compatibility shim for general utilities.

This module has moved to webscout_mcp.core.utils.

Deprecated:
    Import from webscout_mcp.core.utils instead.
    This shim will be removed in a future major version.
"""

from __future__ import annotations

import warnings

from .core.utils import *  # noqa: F401,F403

warnings.warn(
    "webscout_mcp.utils is deprecated, import from webscout_mcp.core.utils instead.",
    DeprecationWarning,
    stacklevel=2,
)
