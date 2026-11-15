"""Compatibility shim: moved to webscout_mcp.core.decision_event.

Deprecated:
    Import from webscout_mcp.core.decision_event instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import decision_event as _impl

warnings.warn(
    "webscout_mcp.decision_event is deprecated, import from webscout_mcp.core.decision_event instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
