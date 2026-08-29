"""Compatibility shim for rag_optimizer module.

This module has been moved to webscout_mcp.extras.rag_optimizer.
This file provides backward compatibility for existing imports.

Deprecated:
    Import from webscout_mcp.extras.rag_optimizer instead.
    This compatibility shim will be removed in a future version.
"""

from __future__ import annotations

import warnings

from .extras.rag_optimizer import *  # noqa: F401,F403
from .extras.rag_optimizer import (
    Chunk,
    RAGResponse,
    SemanticChunker,
    ContextCompressor,
    QueryRewriter,
    RAGOptimizer,
    optimize_rag,
)

warnings.warn(
    "webscout_mcp.rag_optimizer is deprecated, "
    "import from webscout_mcp.extras.rag_optimizer instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "Chunk",
    "RAGResponse",
    "SemanticChunker",
    "ContextCompressor",
    "QueryRewriter",
    "RAGOptimizer",
    "optimize_rag",
]
