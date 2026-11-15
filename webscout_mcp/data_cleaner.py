"""Compatibility shim: moved to webscout_mcp.services.data_cleaner.

Deprecated:
    Import from webscout_mcp.services.data_cleaner instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import data_cleaner as _impl

warnings.warn(
    "webscout_mcp.data_cleaner is deprecated, import from webscout_mcp.services.data_cleaner instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
