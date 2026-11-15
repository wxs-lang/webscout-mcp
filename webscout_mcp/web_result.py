"""Compatibility shim: moved to webscout_mcp.services.web_result.

Deprecated:
    Import from webscout_mcp.services.web_result instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import web_result as _impl

warnings.warn(
    "webscout_mcp.web_result is deprecated, import from webscout_mcp.services.web_result instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
