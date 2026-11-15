"""Compatibility shim: moved to webscout_mcp.providers.crawler (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import crawler as _impl

sys.modules[__name__] = _impl
