"""Compatibility shim: moved to webscout_mcp.providers.local_browser_backend (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import local_browser_backend as _impl

sys.modules[__name__] = _impl
