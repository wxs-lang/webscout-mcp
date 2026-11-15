"""Compatibility shim: moved to webscout_mcp.services.data_exporter (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .services import data_exporter as _impl

sys.modules[__name__] = _impl
