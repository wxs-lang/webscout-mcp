"""Compatibility shim: moved to webscout_mcp.services.exporter.

Deprecated:
    Import from webscout_mcp.services.exporter instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import exporter as _impl

warnings.warn(
    "webscout_mcp.exporter is deprecated, import from webscout_mcp.services.exporter instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
