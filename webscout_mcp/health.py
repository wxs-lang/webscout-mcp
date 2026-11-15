"""Compatibility shim: moved to webscout_mcp.observability.health (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .observability import health as _impl

sys.modules[__name__] = _impl
