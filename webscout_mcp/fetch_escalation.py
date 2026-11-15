"""Compatibility shim: moved to webscout_mcp.services.fetch_escalation.

Deprecated:
    Import from webscout_mcp.services.fetch_escalation instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import fetch_escalation as _impl

warnings.warn(
    "webscout_mcp.fetch_escalation is deprecated, import from webscout_mcp.services.fetch_escalation instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
