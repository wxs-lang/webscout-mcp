"""Compatibility shim: moved to webscout_mcp.providers.serpapi_backend.

Deprecated:
    Import from webscout_mcp.providers.serpapi_backend instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import serpapi_backend as _impl

warnings.warn(
    "webscout_mcp.serpapi_backend is deprecated, import from webscout_mcp.providers.serpapi_backend instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
