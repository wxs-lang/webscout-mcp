"""Compatibility shim: moved to webscout_mcp.observability.search_health.

Deprecated:
    Import from webscout_mcp.observability.search_health instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .observability import search_health as _impl

warnings.warn(
    "webscout_mcp.search_health is deprecated, import from webscout_mcp.observability.search_health instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
