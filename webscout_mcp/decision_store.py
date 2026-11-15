"""Compatibility shim: moved to webscout_mcp.core.decision_store.

Deprecated:
    Import from webscout_mcp.core.decision_store instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import decision_store as _impl

warnings.warn(
    "webscout_mcp.decision_store is deprecated, import from webscout_mcp.core.decision_store instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
