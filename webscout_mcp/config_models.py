"""Compatibility shim: moved to webscout_mcp.core.config_models.

Deprecated:
    Import from webscout_mcp.core.config_models instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import config_models as _impl

warnings.warn(
    "webscout_mcp.config_models is deprecated, import from webscout_mcp.core.config_models instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
