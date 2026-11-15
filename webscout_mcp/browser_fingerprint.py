"""Compatibility shim: moved to webscout_mcp.providers.browser_fingerprint (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import browser_fingerprint as _impl

sys.modules[__name__] = _impl
