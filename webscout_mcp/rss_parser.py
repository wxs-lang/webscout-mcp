"""Compatibility shim: moved to webscout_mcp.services.rss_parser.

Deprecated:
    Import from webscout_mcp.services.rss_parser instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .services import rss_parser as _impl

warnings.warn(
    "webscout_mcp.rss_parser is deprecated, import from webscout_mcp.services.rss_parser instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
