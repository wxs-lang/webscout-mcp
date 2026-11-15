"""Compatibility shim: moved to webscout_mcp.providers.searxng_provider.

Deprecated:
    Import from webscout_mcp.providers.searxng_provider instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import searxng_provider as _impl

warnings.warn(
    "webscout_mcp.searxng_provider is deprecated, import from webscout_mcp.providers.searxng_provider instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
