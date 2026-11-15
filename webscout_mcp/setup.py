"""Compatibility shim: moved to webscout_mcp.server.setup.

Deprecated:
    Import from webscout_mcp.server.setup instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .server import setup as _impl

warnings.warn(
    "webscout_mcp.setup is deprecated, import from webscout_mcp.server.setup instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
