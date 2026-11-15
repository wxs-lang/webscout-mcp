"""Compatibility shim: moved to webscout_mcp.services.data_exporter.

Deprecated:
    Import from webscout_mcp.services.data_exporter instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import data_exporter as _impl

warnings.warn(
    "webscout_mcp.data_exporter is deprecated, import from webscout_mcp.services.data_exporter instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
