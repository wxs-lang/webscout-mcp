"""Compatibility shim: moved to webscout_mcp.eval.advisor_evaluator (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .eval import advisor_evaluator as _impl

sys.modules[__name__] = _impl
