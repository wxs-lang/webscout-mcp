"""Compatibility shim: moved to webscout_mcp.server.builtin_plugins.

Deprecated:
    Import from webscout_mcp.server.builtin_plugins instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .server import builtin_plugins as _impl

warnings.warn(
    "webscout_mcp.builtin_plugins is deprecated, import from webscout_mcp.server.builtin_plugins instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
