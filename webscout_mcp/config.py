"""Compatibility shim for the config module.

This module has moved to webscout_mcp.core.config.

Deprecated:
    Import from webscout_mcp.core.config instead.
    This shim will be removed in a future major version.
"""

from __future__ import annotations

import warnings

# Re-exported wholesale on purpose: this shim must mirror the module it
# wraps, and a hand-maintained list would silently omit anything added
# later. Consumers see the same namespace as before the move.
from .core.config import *  # noqa: F401,F403  # nosec B403 - deliberate re-export

warnings.warn(
    "webscout_mcp.config is deprecated, import from webscout_mcp.core.config instead.",
    DeprecationWarning,
    stacklevel=2,
)
