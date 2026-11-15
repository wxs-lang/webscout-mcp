"""Compatibility shim: moved to webscout_mcp.providers.tls_fetcher.

Deprecated:
    Import from webscout_mcp.providers.tls_fetcher instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import tls_fetcher as _impl

warnings.warn(
    "webscout_mcp.tls_fetcher is deprecated, import from webscout_mcp.providers.tls_fetcher instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
