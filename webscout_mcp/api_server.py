"""Compatibility shim: moved to webscout_mcp.server.api_server (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .server import api_server as _impl

sys.modules[__name__] = _impl
