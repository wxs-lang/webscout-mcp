"""Compatibility shim: moved to webscout_mcp.providers.sitemap.

Deprecated:
    Import from webscout_mcp.providers.sitemap instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import sitemap as _impl

warnings.warn(
    "webscout_mcp.sitemap is deprecated, import from webscout_mcp.providers.sitemap instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
