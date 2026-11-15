"""Compatibility shim: moved to webscout_mcp.providers.provider_registry.

Deprecated:
    Import from webscout_mcp.providers.provider_registry instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import provider_registry as _impl

warnings.warn(
    "webscout_mcp.provider_registry is deprecated, import from webscout_mcp.providers.provider_registry instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
