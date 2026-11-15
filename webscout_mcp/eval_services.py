"""Compatibility shim: moved to webscout_mcp.eval.eval_services (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .eval import eval_services as _impl

sys.modules[__name__] = _impl
