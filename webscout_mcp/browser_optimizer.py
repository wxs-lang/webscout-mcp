"""Compatibility shim: moved to webscout_mcp.providers.browser_optimizer (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import browser_optimizer as _impl

sys.modules[__name__] = _impl
