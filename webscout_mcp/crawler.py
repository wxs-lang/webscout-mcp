"""Compatibility shim: moved to webscout_mcp.providers.crawler.

Deprecated:
    Import from webscout_mcp.providers.crawler instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import crawler as _impl

warnings.warn(
    "webscout_mcp.crawler is deprecated, import from webscout_mcp.providers.crawler instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
