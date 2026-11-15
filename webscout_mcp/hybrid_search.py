"""Compatibility shim: moved to webscout_mcp.services.hybrid_search (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .services import hybrid_search as _impl

sys.modules[__name__] = _impl
