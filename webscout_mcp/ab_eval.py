"""Compatibility shim: moved to webscout_mcp.eval.ab_eval (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .eval import ab_eval as _impl

sys.modules[__name__] = _impl
