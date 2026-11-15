"""Compatibility shim: moved to webscout_mcp.services.fetcher.

Deprecated:
    Import from webscout_mcp.services.fetcher instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import fetcher as _impl

warnings.warn(
    "webscout_mcp.fetcher is deprecated, import from webscout_mcp.services.fetcher instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
