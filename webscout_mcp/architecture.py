"""Compatibility shim: moved to webscout_mcp.core.architecture.

Deprecated:
    Import from webscout_mcp.core.architecture instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import architecture as _impl

warnings.warn(
    "webscout_mcp.architecture is deprecated, import from webscout_mcp.core.architecture instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
