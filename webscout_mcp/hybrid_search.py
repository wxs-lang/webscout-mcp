"""Compatibility shim: moved to webscout_mcp.services.hybrid_search.

Deprecated:
    Import from webscout_mcp.services.hybrid_search instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import hybrid_search as _impl

warnings.warn(
    "webscout_mcp.hybrid_search is deprecated, import from webscout_mcp.services.hybrid_search instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
