"""Compatibility shim: moved to webscout_mcp.providers.provider_router.

Deprecated:
    Import from webscout_mcp.providers.provider_router instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import provider_router as _impl

warnings.warn(
    "webscout_mcp.provider_router is deprecated, import from webscout_mcp.providers.provider_router instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
