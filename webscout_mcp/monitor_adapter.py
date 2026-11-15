"""Compatibility shim: moved to webscout_mcp.observability.monitor_adapter (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .observability import monitor_adapter as _impl

sys.modules[__name__] = _impl
