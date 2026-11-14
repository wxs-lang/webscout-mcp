"""Compatibility shim: moved to webscout_mcp.services.normalization (step-7 reorganization; see docs/ARCHITECTURE_REORG.md).

The sys.modules alias makes every attribute resolve on the real module, including underscore-private names tests monkeypatch."""

import sys

from .services import normalization as _impl

sys.modules[__name__] = _impl
