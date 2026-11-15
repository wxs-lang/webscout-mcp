"""Compatibility shim: moved to webscout_mcp.providers.search_provider_adapter.

Deprecated:
    Import from webscout_mcp.providers.search_provider_adapter instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import search_provider_adapter as _impl

warnings.warn(
    "webscout_mcp.search_provider_adapter is deprecated, import from webscout_mcp.providers.search_provider_adapter instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
