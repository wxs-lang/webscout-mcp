"""Compatibility shim: moved to webscout_mcp.providers.search_recovery.

Deprecated:
    Import from webscout_mcp.providers.search_recovery instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import search_recovery as _impl

warnings.warn(
    "webscout_mcp.search_recovery is deprecated, import from webscout_mcp.providers.search_recovery instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
