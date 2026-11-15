"""Compatibility shim: moved to webscout_mcp.observability.metrics.

Deprecated:
    Import from webscout_mcp.observability.metrics instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .observability import metrics as _impl

warnings.warn(
    "webscout_mcp.metrics is deprecated, import from webscout_mcp.observability.metrics instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
