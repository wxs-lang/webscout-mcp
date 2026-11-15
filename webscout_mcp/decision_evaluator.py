"""Compatibility shim: moved to webscout_mcp.eval.decision_evaluator.

Deprecated:
    Import from webscout_mcp.eval.decision_evaluator instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .eval import decision_evaluator as _impl

warnings.warn(
    "webscout_mcp.decision_evaluator is deprecated, import from webscout_mcp.eval.decision_evaluator instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
