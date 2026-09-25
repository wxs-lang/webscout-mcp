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


def _resolve_run_id() -> str:
    explicit = os.environ.get("WEBSCOUT_RUN_ID") or os.environ.get("JEV_RUN_ID")
    if explicit:
        return explicit
    return f"run-{uuid.uuid4().hex[:12]}"


PROCESS_RUN_ID: str = _resolve_run_id()


def new_trace_id() -> str:
    """Generate a fresh trace id for one MCP operation (fetch or search)."""
    return f"trace-{uuid.uuid4().hex[:16]}"
