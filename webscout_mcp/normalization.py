"""Compatibility shim: moved to webscout_mcp.services.normalization.

Deprecated:
    Import from webscout_mcp.services.normalization instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import normalization as _impl

warnings.warn(
    "webscout_mcp.normalization is deprecated, import from webscout_mcp.services.normalization instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
