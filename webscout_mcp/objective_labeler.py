"""Compatibility shim: moved to webscout_mcp.eval.objective_labeler.

Deprecated:
    Import from webscout_mcp.eval.objective_labeler instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .eval import objective_labeler as _impl

warnings.warn(
    "webscout_mcp.objective_labeler is deprecated, import from webscout_mcp.eval.objective_labeler instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
