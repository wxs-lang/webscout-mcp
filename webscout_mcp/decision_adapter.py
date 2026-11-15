"""Compatibility shim: moved to webscout_mcp.core.decision_adapter.

Deprecated:
    Import from webscout_mcp.core.decision_adapter instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import decision_adapter as _impl

warnings.warn(
    "webscout_mcp.decision_adapter is deprecated, import from webscout_mcp.core.decision_adapter instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
