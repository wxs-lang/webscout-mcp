"""Compatibility shim: moved to webscout_mcp.providers.robots.

Deprecated:
    Import from webscout_mcp.providers.robots instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import robots as _impl

warnings.warn(
    "webscout_mcp.robots is deprecated, import from webscout_mcp.providers.robots instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
