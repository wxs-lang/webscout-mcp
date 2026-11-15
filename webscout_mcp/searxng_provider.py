"""Compatibility shim: moved to webscout_mcp.providers.searxng_provider (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import searxng_provider as _impl

sys.modules[__name__] = _impl
