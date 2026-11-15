"""Compatibility shim: moved to webscout_mcp.providers.sitemap (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import sitemap as _impl

sys.modules[__name__] = _impl
