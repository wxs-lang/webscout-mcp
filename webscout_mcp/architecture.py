"""Compatibility shim: moved to webscout_mcp.core.architecture (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .core import architecture as _impl

sys.modules[__name__] = _impl
