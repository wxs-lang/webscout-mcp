"""Compatibility shim for general utilities.

This module has moved to webscout_mcp.core.utils.

Deprecated:
    Import from webscout_mcp.core.utils instead.
    This shim will be removed in a future major version.
"""

from __future__ import annotations

import warnings

# Re-exported wholesale on purpose: this shim must mirror the module it
# wraps, and a hand-maintained list would silently omit anything added
# later. Consumers see the same namespace as before the move.
from .core.utils import *  # noqa: F401,F403  # nosec B403 - deliberate re-export

warnings.warn(
    "webscout_mcp.utils is deprecated, import from webscout_mcp.core.utils instead.",
    DeprecationWarning,
    stacklevel=2,
)
