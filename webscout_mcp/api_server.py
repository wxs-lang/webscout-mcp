"""Compatibility shim: moved to webscout_mcp.server.api_server.

Deprecated:
    Import from webscout_mcp.server.api_server instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .server import api_server as _impl

warnings.warn(
    "webscout_mcp.api_server is deprecated, import from webscout_mcp.server.api_server instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
