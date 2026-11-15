"""Compatibility shim: moved to webscout_mcp.services.search_optimizer.

Deprecated:
    Import from webscout_mcp.services.search_optimizer instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import search_optimizer as _impl

warnings.warn(
    "webscout_mcp.search_optimizer is deprecated, import from webscout_mcp.services.search_optimizer instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
