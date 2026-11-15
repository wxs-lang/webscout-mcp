"""Compatibility shim: moved to webscout_mcp.services.rss_parser (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .services import rss_parser as _impl

sys.modules[__name__] = _impl
