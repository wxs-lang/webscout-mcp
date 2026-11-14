"""Compatibility shim: moved to webscout_mcp.core.url_canonicalize (step-7 reorganization; see docs/ARCHITECTURE_REORG.md).

The sys.modules alias makes every attribute resolve on the real module, including underscore-private names that tests monkeypatch."""

import sys

from .core import url_canonicalize as _impl

sys.modules[__name__] = _impl
