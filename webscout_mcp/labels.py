"""Compatibility shim: moved to webscout_mcp.services.labels.

Deprecated:
    Import from webscout_mcp.services.labels instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import labels as _impl

warnings.warn(
    "webscout_mcp.labels is deprecated, import from webscout_mcp.services.labels instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
