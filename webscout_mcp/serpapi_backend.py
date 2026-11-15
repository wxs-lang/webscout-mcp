"""Compatibility shim: moved to webscout_mcp.providers.serpapi_backend (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .providers import serpapi_backend as _impl

sys.modules[__name__] = _impl
