"""Compatibility shim: moved to webscout_mcp.observability.monitor_adapter.

Deprecated:
    Import from webscout_mcp.observability.monitor_adapter instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .observability import monitor_adapter as _impl

warnings.warn(
    "webscout_mcp.monitor_adapter is deprecated, import from webscout_mcp.observability.monitor_adapter instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
