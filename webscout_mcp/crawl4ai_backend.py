"""Compatibility shim: moved to webscout_mcp.providers.crawl4ai_backend.

Deprecated:
    Import from webscout_mcp.providers.crawl4ai_backend instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import crawl4ai_backend as _impl

warnings.warn(
    "webscout_mcp.crawl4ai_backend is deprecated, import from webscout_mcp.providers.crawl4ai_backend instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
