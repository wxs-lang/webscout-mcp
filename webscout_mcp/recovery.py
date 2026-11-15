"""Compatibility shim: moved to webscout_mcp.orchestration.recovery.

Deprecated:
    Import from webscout_mcp.orchestration.recovery instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .orchestration import recovery as _impl

warnings.warn(
    "webscout_mcp.recovery is deprecated, import from webscout_mcp.orchestration.recovery instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
