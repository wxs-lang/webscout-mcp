"""Compatibility shim: moved to webscout_mcp.observability.health.

Deprecated:
    Import from webscout_mcp.observability.health instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .observability import health as _impl

warnings.warn(
    "webscout_mcp.health is deprecated, import from webscout_mcp.observability.health instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
