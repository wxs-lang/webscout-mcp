"""Core infrastructure layer.

Contains the primitives everything else builds on: the standard error taxonomy,
configuration, caching and logging. These modules have no dependencies on the
layers above them, which is what makes the layering meaningful rather than
cosmetic.

Import compatibility: every module here is still reachable from its historical
flat path (`webscout_mcp.errors` etc.) through a deprecation shim, so this
reorganisation cannot break existing callers.
"""

from __future__ import annotations

__all__ = ["errors"]
