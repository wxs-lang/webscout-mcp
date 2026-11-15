"""Compatibility shim: moved to webscout_mcp.providers.tls_impersonation.

Deprecated:
    Import from webscout_mcp.providers.tls_impersonation instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import tls_impersonation as _impl

warnings.warn(
    "webscout_mcp.tls_impersonation is deprecated, import from webscout_mcp.providers.tls_impersonation instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
