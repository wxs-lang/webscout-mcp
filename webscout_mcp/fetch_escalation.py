"""Compatibility shim: moved to webscout_mcp.services.fetch_escalation (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .services import fetch_escalation as _impl

sys.modules[__name__] = _impl
