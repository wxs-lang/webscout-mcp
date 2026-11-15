"""Compatibility shim: moved to webscout_mcp.providers.search_providers.

Deprecated:
    Import from webscout_mcp.providers.search_providers instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import search_providers as _impl

warnings.warn(
    "webscout_mcp.search_providers is deprecated, import from webscout_mcp.providers.search_providers instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
