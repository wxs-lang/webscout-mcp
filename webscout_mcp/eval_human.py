"""Compatibility shim: moved to webscout_mcp.eval.eval_human.

Deprecated:
    Import from webscout_mcp.eval.eval_human instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .eval import eval_human as _impl

warnings.warn(
    "webscout_mcp.eval_human is deprecated, import from webscout_mcp.eval.eval_human instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
