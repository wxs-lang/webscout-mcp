"""Compatibility shim: moved to webscout_mcp.services.ocr_engine.

Deprecated:
    Import from webscout_mcp.services.ocr_engine instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import ocr_engine as _impl

warnings.warn(
    "webscout_mcp.ocr_engine is deprecated, import from webscout_mcp.services.ocr_engine instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
