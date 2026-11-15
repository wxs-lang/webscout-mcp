"""Compatibility shim: moved to webscout_mcp.services.labels (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .services import labels as _impl

sys.modules[__name__] = _impl
