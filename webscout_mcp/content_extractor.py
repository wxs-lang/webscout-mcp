"""Compatibility shim: moved to webscout_mcp.services.content_extractor (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .services import content_extractor as _impl

sys.modules[__name__] = _impl
