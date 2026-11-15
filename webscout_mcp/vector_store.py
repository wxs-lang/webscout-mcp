"""Compatibility shim: moved to webscout_mcp.services.vector_store.

Deprecated:
    Import from webscout_mcp.services.vector_store instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import vector_store as _impl

warnings.warn(
    "webscout_mcp.vector_store is deprecated, import from webscout_mcp.services.vector_store instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
