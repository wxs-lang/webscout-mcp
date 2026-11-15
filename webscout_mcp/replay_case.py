"""Compatibility shim: moved to webscout_mcp.core.replay_case (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .core import replay_case as _impl

sys.modules[__name__] = _impl
