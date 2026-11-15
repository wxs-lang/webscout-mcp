"""Compatibility shim: moved to webscout_mcp.services.extractor.

Deprecated:
    Import from webscout_mcp.services.extractor instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import extractor as _impl

warnings.warn(
    "webscout_mcp.extractor is deprecated, import from webscout_mcp.services.extractor instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
