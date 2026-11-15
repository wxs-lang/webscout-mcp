"""Compatibility shim: moved to webscout_mcp.services.jev_client.

Deprecated:
    Import from webscout_mcp.services.jev_client instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import jev_client as _impl

warnings.warn(
    "webscout_mcp.jev_client is deprecated, import from webscout_mcp.services.jev_client instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
