"""Compatibility shim: moved to webscout_mcp.core.user_agent.

Deprecated:
    Import from webscout_mcp.core.user_agent instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import user_agent as _impl

warnings.warn(
    "webscout_mcp.user_agent is deprecated, import from webscout_mcp.core.user_agent instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
