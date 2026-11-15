"""Compatibility shim: moved to webscout_mcp.security.url_safety.

Deprecated:
    Import from webscout_mcp.security.url_safety instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .security import url_safety as _impl

warnings.warn(
    "webscout_mcp.url_safety is deprecated, import from webscout_mcp.security.url_safety instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
