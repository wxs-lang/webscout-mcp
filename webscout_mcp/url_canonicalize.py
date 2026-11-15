"""Compatibility shim: moved to webscout_mcp.core.url_canonicalize.

Deprecated:
    Import from webscout_mcp.core.url_canonicalize instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import url_canonicalize as _impl

warnings.warn(
    "webscout_mcp.url_canonicalize is deprecated, import from webscout_mcp.core.url_canonicalize instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
