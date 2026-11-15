"""Compatibility shim: moved to webscout_mcp.core.metadata_sanitize.

Deprecated:
    Import from webscout_mcp.core.metadata_sanitize instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import metadata_sanitize as _impl

warnings.warn(
    "webscout_mcp.metadata_sanitize is deprecated, import from webscout_mcp.core.metadata_sanitize instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
