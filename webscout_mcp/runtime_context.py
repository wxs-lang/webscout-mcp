"""Compatibility shim: moved to webscout_mcp.core.runtime_context.

Deprecated:
    Import from webscout_mcp.core.runtime_context instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import runtime_context as _impl

warnings.warn(
    "webscout_mcp.runtime_context is deprecated, import from webscout_mcp.core.runtime_context instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
