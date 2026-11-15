"""Compatibility shim: moved to webscout_mcp.eval.eval_runners (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .eval import eval_runners as _impl

sys.modules[__name__] = _impl
