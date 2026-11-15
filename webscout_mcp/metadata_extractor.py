"""Compatibility shim: moved to webscout_mcp.services.metadata_extractor.

Deprecated:
    Import from webscout_mcp.services.metadata_extractor instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import metadata_extractor as _impl

warnings.warn(
    "webscout_mcp.metadata_extractor is deprecated, import from webscout_mcp.services.metadata_extractor instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
