"""Compatibility shim: moved to webscout_mcp.providers.robots (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import robots as _impl

sys.modules[__name__] = _impl
