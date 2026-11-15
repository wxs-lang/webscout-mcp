"""Compatibility shim: moved to webscout_mcp.server.plugin_system.

Deprecated:
    Import from webscout_mcp.server.plugin_system instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .server import plugin_system as _impl

warnings.warn(
    "webscout_mcp.plugin_system is deprecated, import from webscout_mcp.server.plugin_system instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
