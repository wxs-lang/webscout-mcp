"""Compatibility shim: moved to webscout_mcp.eval.eval_runners.

Deprecated:
    Import from webscout_mcp.eval.eval_runners instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .eval import eval_runners as _impl

warnings.warn(
    "webscout_mcp.eval_runners is deprecated, import from webscout_mcp.eval.eval_runners instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
