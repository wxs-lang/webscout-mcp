"""Compatibility shim: moved to webscout_mcp.providers.provider_registry (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import provider_registry as _impl

sys.modules[__name__] = _impl
