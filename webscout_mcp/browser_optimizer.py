"""Compatibility shim: moved to webscout_mcp.providers.browser_optimizer.

Deprecated:
    Import from webscout_mcp.providers.browser_optimizer instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import browser_optimizer as _impl

warnings.warn(
    "webscout_mcp.browser_optimizer is deprecated, import from webscout_mcp.providers.browser_optimizer instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
