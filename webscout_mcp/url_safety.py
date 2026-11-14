"""Compatibility shim: moved to webscout_mcp.security.url_safety (step-7 reorganization; see docs/ARCHITECTURE_REORG.md).

The sys.modules alias makes every attribute resolve on the real module, including underscore-private names that tests monkeypatch."""

import sys

from .security import url_safety as _impl

sys.modules[__name__] = _impl
