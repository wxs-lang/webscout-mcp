"""Compatibility shim: moved to webscout_mcp.services.translator.

Deprecated:
    Import from webscout_mcp.services.translator instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import translator as _impl

warnings.warn(
    "webscout_mcp.translator is deprecated, import from webscout_mcp.services.translator instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
