"""Compatibility shim: moved to webscout_mcp.eval.ab_eval.

Deprecated:
    Import from webscout_mcp.eval.ab_eval instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .eval import ab_eval as _impl

warnings.warn(
    "webscout_mcp.ab_eval is deprecated, import from webscout_mcp.eval.ab_eval instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
