"""Compatibility shim: moved to webscout_mcp.services.pdf_processor.

Deprecated:
    Import from webscout_mcp.services.pdf_processor instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import pdf_processor as _impl

warnings.warn(
    "webscout_mcp.pdf_processor is deprecated, import from webscout_mcp.services.pdf_processor instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
