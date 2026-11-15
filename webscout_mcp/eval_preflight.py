"""Compatibility shim: moved to webscout_mcp.eval.eval_preflight (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .eval import eval_preflight as _impl

sys.modules[__name__] = _impl
