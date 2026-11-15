"""Compatibility shim: moved to webscout_mcp.services.incremental.

Deprecated:
    Import from webscout_mcp.services.incremental instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import incremental as _impl

warnings.warn(
    "webscout_mcp.incremental is deprecated, import from webscout_mcp.services.incremental instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
