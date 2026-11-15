"""Compatibility shim: moved to webscout_mcp.providers.crawl4ai_backend (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import crawl4ai_backend as _impl

sys.modules[__name__] = _impl
