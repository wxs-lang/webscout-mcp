"""Compatibility shim: moved to webscout_mcp.eval.eval_human (step-7 reorganization; see docs/ARCHITECTURE_REORG.md).

The sys.modules alias makes every attribute resolve on the real module, including underscore-private names tests monkeypatch."""

import sys

from .eval import eval_human as _impl

sys.modules[__name__] = _impl
