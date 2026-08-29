"""Compatibility shim for knowledge_graph module.

This module has been moved to webscout_mcp.extras.knowledge_graph.
This file provides backward compatibility for existing imports.

Deprecated:
    Import from webscout_mcp.extras.knowledge_graph instead.
    This compatibility shim will be removed in a future version.
"""

from __future__ import annotations

import warnings

from .extras.knowledge_graph import *  # noqa: F401,F403
from .extras.knowledge_graph import (
    Entity,
    Relationship,
    KnowledgeGraph,
    KnowledgeGraphBuilder,
    build_knowledge_graph,
)

warnings.warn(
    "webscout_mcp.knowledge_graph is deprecated, "
    "import from webscout_mcp.extras.knowledge_graph instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "Entity",
    "Relationship",
    "KnowledgeGraph",
    "KnowledgeGraphBuilder",
    "build_knowledge_graph",
]
