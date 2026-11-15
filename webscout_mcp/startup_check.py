"""Compatibility shim: moved to webscout_mcp.server.startup_check.

Deprecated:
    Import from webscout_mcp.server.startup_check instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .server import startup_check as _impl

warnings.warn(
    "webscout_mcp.startup_check is deprecated, import from webscout_mcp.server.startup_check instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
