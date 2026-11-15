"""Compatibility shim: moved to webscout_mcp.core.decision_adapter (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .core import decision_adapter as _impl

sys.modules[__name__] = _impl
