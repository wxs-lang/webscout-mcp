"""Compatibility shim: moved to webscout_mcp.eval.eval_services.

Deprecated:
    Import from webscout_mcp.eval.eval_services instead.
    Step-7 reorganization; see docs/ARCHITECTURE_REORG.md.
"""

import sys
import warnings

from .eval import eval_services as _impl

warnings.warn(
    "webscout_mcp.eval_services is deprecated, import from webscout_mcp.eval.eval_services instead.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[__name__] = _impl
