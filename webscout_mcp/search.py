"""Compatibility shim: moved to webscout_mcp.services.search.

Deprecated:
    Import from webscout_mcp.services.search instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import search as _impl

warnings.warn(
    "webscout_mcp.search is deprecated, import from webscout_mcp.services.search instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
