"""Compatibility shim: moved to webscout_mcp.eval.advisor_evaluator.

Deprecated:
    Import from webscout_mcp.eval.advisor_evaluator instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .eval import advisor_evaluator as _impl

warnings.warn(
    "webscout_mcp.advisor_evaluator is deprecated, import from webscout_mcp.eval.advisor_evaluator instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
