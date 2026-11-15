"""Compatibility shim: moved to webscout_mcp.core.async_utils (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .core import async_utils as _impl

sys.modules[__name__] = _impl
