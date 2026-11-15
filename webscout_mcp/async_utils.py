"""Compatibility shim: moved to webscout_mcp.core.async_utils.

Deprecated:
    Import from webscout_mcp.core.async_utils instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import async_utils as _impl

warnings.warn(
    "webscout_mcp.async_utils is deprecated, import from webscout_mcp.core.async_utils instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
