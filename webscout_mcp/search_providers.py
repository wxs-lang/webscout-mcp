"""Compatibility shim: moved to webscout_mcp.providers.search_providers (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import search_providers as _impl

sys.modules[__name__] = _impl
