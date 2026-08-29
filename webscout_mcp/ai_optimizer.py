"""Compatibility shim for ai_optimizer module.

This module has been moved to webscout_mcp.extras.ai_optimizer.
This file provides backward compatibility for existing imports.

Deprecated:
    Import from webscout_mcp.extras.ai_optimizer instead.
    This compatibility shim will be removed in a future version.
"""

from __future__ import annotations

import warnings

from .extras.ai_optimizer import *  # noqa: F401,F403
from .extras.ai_optimizer import (
    AIResponse,
    PromptTemplate,
    PromptEngineer,
    OutputValidator,
    HallucinationDetector,
    ModelOptimizer,
    AIOptimizer,
    optimize_ai_processing,
)

warnings.warn(
    "webscout_mcp.ai_optimizer is deprecated, "
    "import from webscout_mcp.extras.ai_optimizer instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "AIResponse",
    "PromptTemplate",
    "PromptEngineer",
    "OutputValidator",
    "HallucinationDetector",
    "ModelOptimizer",
    "AIOptimizer",
    "optimize_ai_processing",
]
