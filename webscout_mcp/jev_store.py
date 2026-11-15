"""Compatibility shim: moved to webscout_mcp.services.jev_store (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .services import jev_store as _impl

sys.modules[__name__] = _impl
