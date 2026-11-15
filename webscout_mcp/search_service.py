"""Compatibility shim: moved to webscout_mcp.orchestration.search_service.

Deprecated:
    Import from webscout_mcp.orchestration.search_service instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .orchestration import search_service as _impl

warnings.warn(
    "webscout_mcp.search_service is deprecated, import from webscout_mcp.orchestration.search_service instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
