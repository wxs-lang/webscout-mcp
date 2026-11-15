"""Compatibility shim: moved to webscout_mcp.server.setup (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .server import setup as _impl

sys.modules[__name__] = _impl
