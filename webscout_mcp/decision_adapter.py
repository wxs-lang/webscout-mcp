"""Adapters that convert Fetch/Search production results into DecisionEvents.

These functions are pure data-transform + best-effort store write. They MUST
NOT change any production routing, recovery, or return values. Every call is
wrapped so that a store failure is logged and swallowed.

Hook points:
  * FetchService.fetch() — after recovery execution, before returning
    FetchRouteResult.
  * SearchService.search() — at each final return (success / empty / error /
    stop / cache-hit).
"""

from __future__ import annotations

import time
from typing import Any

from .decision_event import (
    DecisionDomain,
    DecisionEvent,
    DecisionStage,
    query_hash,
    sanitized_url_features,
)
from .logging_config import get_logger

log = get_logger(__name__)


def _telemetry_enabled() -> bool:
    import os

    val = os.environ.get("WEBSCOUT_DECISION_TELEMETRY", "1").lower()
    return val not in ("0", "false", "no", "off")


def _safe_record(event: DecisionEvent) -> None:
    """Record a DecisionEvent best-effort. Never raises."""
    if not _telemetry_enabled():
        return
    try:
        from . import decision_store

        decision_store.record_event(event)
    except Exception:
        log.debug("decision telemetry record failed", exc_info=True)


# ---------------------------------------------------------------------------
# Fetch adapter
# ---------------------------------------------------------------------------


def record_fetch_decision(
    *,
    request: Any,
    primary: Any,
    final: Any,
    recovery: Any,
    recovery_outcome: str,
    primary_provider: str,
    browser_attempted: bool,
    browser_success: bool,
    fallback_used: bool,
    cache_hit: bool = False,
    snapshot_hit: bool = False,
    trace_id: str = "",
    run_id: str = "",
    jev_call_id: str = "",
    started_at: float = 0.0,
) -> None:
    """Record a Fetch DecisionEvent from FetchService.fetch() state.

    All arguments are read-only references; this function never mutates them.
    """
    try:
        url = getattr(request, "url", "") or ""
        max_chars = getattr(request, "max_chars", 8000)
        start_char = getattr(request, "start_char", 0)
        output_format = getattr(request, "output_format", "markdown")
        extract = getattr(request, "extract", True)
        bypass_cache = getattr(request, "bypass_cache", False)

        reason = getattr(recovery, "reason", None)
        action = getattr(recovery, "action", None)
        reason_val = reason.value if hasattr(reason, "value") else str(reason or "")
        action_val = action.value if hasattr(action, "value") else str(action or "")

        primary_status = getattr(primary, "status", "") or ""
        primary_status_code = getattr(primary, "status_code", 0) or 0
        final_status = getattr(final, "status", "") or ""

        # Outcome features — only scalars, no body text.
        web_result = getattr(final, "web_result", None)
        content_chars = 0
        pre_limit_chars = 0
        returned_chars = 0
        truncated = False
        continuation_available = False
        extraction_success = False
        if web_result is not None:
            meta = getattr(web_result, "metadata", {}) or {}
            content_chars = int(meta.get("content_chars", 0) or 0)
            pre_limit_chars = int(meta.get("pre_limit_content_chars", 0) or 0)
            returned_chars = int(meta.get("returned_content_chars", 0) or 0)
            truncated = bool(meta.get("truncated_by_output_limit", False))
            cont = meta.get("continuation")
            if isinstance(cont, dict):
                continuation_available = bool(cont.get("has_more", False))
            extraction_success = bool(meta.get("extracted", False))
        else:
            # Fall back to FetchResponse fields if web_result not set.
            content = getattr(final, "content", "") or ""
            content_chars = len(content) if isinstance(content, str) else 0
            returned_chars = content_chars

        http_group = ""
        if primary_status_code:
            if 200 <= primary_status_code < 300:
                http_group = "2xx"
            elif 300 <= primary_status_code < 400:
                http_group = "3xx"
            elif 400 <= primary_status_code < 500:
                http_group = "4xx"
            elif primary_status_code >= 500:
                http_group = "5xx"

        request_features = {
            "url": sanitized_url_features(url),
            "extract": extract,
            "output_format": output_format,
            "max_chars": max_chars,
            "start_char": start_char,
            "bypass_cache": bypass_cache,
            "cache_hit": cache_hit,
            "snapshot_hit": snapshot_hit,
        }
        outcome_features = {
            "status": final_status,
            "primary_status": primary_status,
            "http_status_group": http_group,
            "http_status_code": primary_status_code,
            "content_chars": content_chars,
            "pre_limit_chars": pre_limit_chars,
            "returned_chars": returned_chars,
            "truncated": truncated,
            "continuation_available": continuation_available,
            "extraction_success": extraction_success,
            "browser_used": browser_attempted,
            "browser_success": browser_success,
            "fallback_used": fallback_used,
            "cache_hit": cache_hit,
            "snapshot_hit": snapshot_hit,
        }

        event = DecisionEvent(
            trace_id=trace_id,
            run_id=run_id,
            domain=DecisionDomain.FETCH,
            stage=DecisionStage.FINAL,
            subject=primary_provider,
            observed_status=final_status,
            deterministic_reason=reason_val,
            deterministic_action=action_val,
            production_action=action_val,
            production_outcome=recovery_outcome,
            started_at=started_at or time.time(),
            completed_at=time.time(),
            latency_ms=max(0.0, (time.time() - (started_at or time.time())) * 1000),
            request_features=request_features,
            outcome_features=outcome_features,
            jev_call_id=jev_call_id,
        )
        _safe_record(event)
    except Exception:
        log.debug("fetch decision record failed", exc_info=True)


# ---------------------------------------------------------------------------
# Search adapter
# ---------------------------------------------------------------------------


def record_search_decision(
    *,
    request: Any,
    response: Any,
    final_decision: Any,
    provider_attempt_count: int = 0,
    fallback_count: int = 0,
    circuit_skips: int = 0,
    unavailable_skips: int = 0,
    trace_id: str = "",
    run_id: str = "",
    jev_call_id: str = "",
    started_at: float = 0.0,
    cache_hit: bool = False,
) -> None:
    """Record a Search DecisionEvent from SearchService.search() state."""
    try:
        query = getattr(request, "query", "") or ""
        max_results = getattr(request, "max_results", 10)
        safe_search = getattr(request, "safe_search", True)
        region = getattr(request, "region", "")
        language = getattr(request, "language", "")
        country = getattr(request, "country", "")

        reason = ""
        action = ""
        if final_decision is not None:
            r = getattr(final_decision, "reason", None)
            a = getattr(final_decision, "action", None)
            reason = r.value if hasattr(r, "value") else str(r or "")
            action = a.value if hasattr(a, "value") else str(a or "")

        # If decision is None (e.g. cache hit before classification), derive
        # from response status.
        if not action:
            status = getattr(response, "status", None)
            status_val = status.value if hasattr(status, "value") else str(status or "")
            if status_val == "success":
                reason = "RESULT_AVAILABLE"
                action = "ACCEPT"
            elif status_val == "empty":
                reason = "ALL_EMPTY"
                action = "RETURN_EMPTY"
            else:
                reason = "ALL_FAILED"
                action = "RETURN_ERROR"

        resp_status = getattr(response, "status", None)
        status_val = resp_status.value if hasattr(resp_status, "value") else str(resp_status or "")
        result_count = len(getattr(response, "results", []) or [])
        final_provider = getattr(response, "provider", "") or ""
        latency_ms = float(getattr(response, "latency_ms", 0.0) or 0.0)

        # Production outcome mapping.
        if action == "ACCEPT":
            outcome = "accepted"
        elif action == "TRY_NEXT_PROVIDER":
            outcome = "next_provider"
        elif action == "RETURN_EMPTY":
            outcome = "returned_empty"
        elif action == "RETURN_ERROR":
            outcome = "returned_error"
        elif action == "STOP":
            outcome = "stopped"
        else:
            outcome = "no_action"

        request_features = {
            "query_hash": query_hash(query),
            "query_length": len(query),
            "max_results": max_results,
            "safe_search": safe_search,
            "region": region,
            "language": language,
            "country": country,
            "cache_hit": cache_hit,
        }
        outcome_features = {
            "status": status_val,
            "result_count": result_count,
            "provider_attempt_count": provider_attempt_count,
            "final_provider": final_provider,
            "fallback_count": fallback_count,
            "circuit_skips": circuit_skips,
            "unavailable_skips": unavailable_skips,
            "latency_ms": latency_ms,
        }

        event = DecisionEvent(
            trace_id=trace_id,
            run_id=run_id,
            domain=DecisionDomain.SEARCH,
            stage=DecisionStage.FINAL,
            subject=final_provider,
            observed_status=status_val,
            deterministic_reason=reason,
            deterministic_action=action,
            production_action=action,
            production_outcome=outcome,
            started_at=started_at or time.time(),
            completed_at=time.time(),
            latency_ms=latency_ms or max(0.0, (time.time() - (started_at or time.time())) * 1000),
            request_features=request_features,
            outcome_features=outcome_features,
            jev_call_id=jev_call_id,
        )
        _safe_record(event)
    except Exception:
        log.debug("search decision record failed", exc_info=True)
