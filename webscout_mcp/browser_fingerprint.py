"""Compatibility shim: moved to webscout_mcp.providers.browser_fingerprint.

Deprecated:
    Import from webscout_mcp.providers.browser_fingerprint instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .providers import browser_fingerprint as _impl

warnings.warn(
    "webscout_mcp.browser_fingerprint is deprecated, import from webscout_mcp.providers.browser_fingerprint instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
