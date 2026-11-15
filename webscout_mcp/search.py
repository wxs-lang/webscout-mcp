"""Compatibility shim: moved to webscout_mcp.services.search (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .services import search as _impl

sys.modules[__name__] = _impl
