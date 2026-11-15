"""Compatibility shim: moved to webscout_mcp.orchestration.jev_shadow.

Deprecated:
    Import from webscout_mcp.orchestration.jev_shadow instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .orchestration import jev_shadow as _impl

warnings.warn(
    "webscout_mcp.jev_shadow is deprecated, import from webscout_mcp.orchestration.jev_shadow instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
