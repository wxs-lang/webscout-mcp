"""Compatibility shim: moved to webscout_mcp.core.exceptions (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .core import exceptions as _impl

sys.modules[__name__] = _impl
