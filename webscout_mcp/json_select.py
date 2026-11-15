"""Compatibility shim: moved to webscout_mcp.core.json_select.

Deprecated:
    Import from webscout_mcp.core.json_select instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import json_select as _impl

warnings.warn(
    "webscout_mcp.json_select is deprecated, import from webscout_mcp.core.json_select instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
