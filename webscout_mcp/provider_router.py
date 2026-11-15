"""Compatibility shim: moved to webscout_mcp.providers.provider_router (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import provider_router as _impl

sys.modules[__name__] = _impl
