"""Compatibility shim: moved to webscout_mcp.services.seo_analyzer.

Deprecated:
    Import from webscout_mcp.services.seo_analyzer instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import seo_analyzer as _impl

warnings.warn(
    "webscout_mcp.seo_analyzer is deprecated, import from webscout_mcp.services.seo_analyzer instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
