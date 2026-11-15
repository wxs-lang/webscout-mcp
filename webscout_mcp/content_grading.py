"""Compatibility shim: moved to webscout_mcp.core.content_grading.

Deprecated:
    Import from webscout_mcp.core.content_grading instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import content_grading as _impl

warnings.warn(
    "webscout_mcp.content_grading is deprecated, import from webscout_mcp.core.content_grading instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
