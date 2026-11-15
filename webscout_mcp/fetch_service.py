"""Compatibility shim: moved to webscout_mcp.orchestration.fetch_service.

Deprecated:
    Import from webscout_mcp.orchestration.fetch_service instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .orchestration import fetch_service as _impl

warnings.warn(
    "webscout_mcp.fetch_service is deprecated, import from webscout_mcp.orchestration.fetch_service instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
