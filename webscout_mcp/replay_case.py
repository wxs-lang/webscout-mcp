"""Compatibility shim: moved to webscout_mcp.core.replay_case.

Deprecated:
    Import from webscout_mcp.core.replay_case instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .core import replay_case as _impl

warnings.warn(
    "webscout_mcp.replay_case is deprecated, import from webscout_mcp.core.replay_case instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
