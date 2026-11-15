"""Compatibility shim: moved to webscout_mcp.core.decision_event (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .core import decision_event as _impl

sys.modules[__name__] = _impl
