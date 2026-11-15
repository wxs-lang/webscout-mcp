"""Compatibility shim: moved to webscout_mcp.core.exceptions.

Deprecated:
    Import from webscout_mcp.core.exceptions instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import exceptions as _impl

warnings.warn(
    "webscout_mcp.exceptions is deprecated, import from webscout_mcp.core.exceptions instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
