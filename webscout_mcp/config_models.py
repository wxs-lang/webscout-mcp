"""Compatibility shim: moved to webscout_mcp.core.config_models (step-7 reorganization; see docs/ARCHITECTURE_REORG.md)."""

import sys

from .core import config_models as _impl

sys.modules[__name__] = _impl
