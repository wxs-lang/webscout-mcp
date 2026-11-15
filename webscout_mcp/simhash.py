"""Compatibility shim: moved to webscout_mcp.services.simhash.

Deprecated:
    Import from webscout_mcp.services.simhash instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import simhash as _impl

warnings.warn(
    "webscout_mcp.simhash is deprecated, import from webscout_mcp.services.simhash instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
