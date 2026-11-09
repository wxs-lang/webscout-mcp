"""Neutral runtime context: process run id and per-operation trace id.

This module exists so that DecisionEvent and Jev Shadow share the SAME
run_id and trace_id without either layer depending on the other.

- PROCESS_RUN_ID: stable for the lifetime of the process. Override via
  WEBSCOUT_RUN_ID (JEV_RUN_ID accepted as legacy alias).
- new_trace_id(): generate a fresh per-operation trace id.
"""

from __future__ import annotations

import os
import uuid
from typing import Any


def _resolve_run_id() -> str:
    explicit = os.environ.get("WEBSCOUT_RUN_ID") or os.environ.get("JEV_RUN_ID")
    if explicit:
        return explicit
    return f"run-{uuid.uuid4().hex[:12]}"


PROCESS_RUN_ID: str = _resolve_run_id()


def new_trace_id() -> str:
    """Generate a fresh trace id for one MCP operation (fetch or search)."""
    return f"trace-{uuid.uuid4().hex[:16]}"


# Modules that captured ``PROCESS_RUN_ID`` by value at import time
# (``from .runtime_context import PROCESS_RUN_ID``) or read ``JEV_RUN_ID`` at
# import. The evaluation CLI must be able to flip the run id mid-process, so
# ``set_process_run_id_for_evaluation`` patches their already-bound names.
_EVAL_BOUND_MODULES = (
    "webscout_mcp.fetch_service",
    "webscout_mcp.search_service",
    "webscout_mcp.jev_shadow",
)


def set_process_run_id_for_evaluation(run_id: str) -> None:
    """Force the process-wide run id for the OFFLINE EVALUATION CLI only.

    WARNING: this is an evaluation-only escape hatch. It MUST NOT be called on
    the production request path. It deliberately reaches into modules that
    bound ``PROCESS_RUN_ID`` by value at import time (a plain reassignment of
    ``runtime_context.PROCESS_RUN_ID`` would not update those names), so the
    evaluation harness can re-segment a sampled batch without restarting the
    process.

    Effects:
      * sets ``WEBSCOUT_RUN_ID`` and ``JEV_RUN_ID`` env vars (late importers
        read them at import);
      * sets this module's ``PROCESS_RUN_ID`` global;
      * patches the already-imported ``PROCESS_RUN_ID`` binding in
        ``fetch_service`` / ``search_service`` / ``jev_shadow`` ONLY when they
        are already present in ``sys.modules`` (never force-imported).
    """
    global PROCESS_RUN_ID

    run_id = run_id or ""
    os.environ["WEBSCOUT_RUN_ID"] = run_id
    os.environ["JEV_RUN_ID"] = run_id
    PROCESS_RUN_ID = run_id

    import sys

    for mod_name in _EVAL_BOUND_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "PROCESS_RUN_ID"):
            any_mod: Any = mod
            any_mod.PROCESS_RUN_ID = run_id
