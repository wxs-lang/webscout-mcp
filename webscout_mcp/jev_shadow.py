"""JevShadow — shadow-only evaluation orchestration for WebScout.

This module owns:
  * building the sanitized state that gets sent to Jev
  * recording ShadowRecord entries (in-memory, bounded)
  * maintaining Jev shadow metrics (calls, latency p50/p95, agreement)

Hard guarantees:
  * Jev is never consulted before the production decision is made.
  * Any Jev error/timeout/malformed response is swallowed and recorded.
  * Sensitive material (URL credentials, query strings, cookies, tokens,
    internal IPs, full headers) is stripped before being handed to Jev.
  * When JEV_ENABLED=false, this module is a no-op and adds zero overhead
    beyond a config check.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections import deque
from typing import Any

from .fetch_escalation import FetchEscalationDecision
from .fetch_provider import FetchResponse
from .jev_client import (
    JEV_DECISION_SCHEMA_VERSION,
    JevClient,
    JevDecision,
    stable_hash,
)
from .jev_store import append_record
from .logging_config import get_logger
from .observability import safe_host
from .search_provider import SearchResult

log = get_logger(__name__)

_MAX_RECORDS = 5000  # in-memory ring buffer; never unbounded


def _process_run_id() -> str:
    """Per-process run id. Override with JEV_RUN_ID env; otherwise a random
    hex id that isolates one sampling batch from another."""
    return os.environ.get("JEV_RUN_ID") or f"run-{uuid.uuid4().hex[:10]}"


PROCESS_RUN_ID: str = _process_run_id()


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    head = text[: int(max_chars * 0.8)]
    tail = text[-int(max_chars * 0.1) :]
    return head + " ...[truncated]... " + tail


def build_fetch_state(
    response: FetchResponse,
    rule_decision: FetchEscalationDecision | None,
    max_chars: int,
) -> dict[str, Any]:
    """Build the sanitized fetch-side state sent to Jev.

    Only safe, deterministic fields are included. No URL path/query, no
    headers, no cookies, no tokens. Content is truncated to ``max_chars``.
    """
    excerpt = _truncate(response.content or "", max_chars)
    state: dict[str, Any] = {
        "task": "fetch_quality",
        "host": safe_host(response.final_url or response.url),
        "title": (response.title or "")[:500],
        "content_excerpt": excerpt,
        "content_length": len(response.content or ""),
        "content_type": (response.content_type or "")[:120],
        "http_status": int(response.status_code or 0),
        "extracted": bool(response.extracted),
        "empty_content": not (response.content or "").strip(),
        "truncated": len(response.content or "") > len(excerpt),
        "backend": response.provider or "unknown",
        "rule_escalate": bool(rule_decision and rule_decision.escalate),
        "rule_reason": (rule_decision.reason_code.value if rule_decision and rule_decision.reason_code else None),
    }
    return state


def build_search_state(query: str, result: SearchResult, max_chars: int) -> dict[str, Any]:
    """Build the sanitized search-side state sent to Jev."""
    return {
        "task": "result_relevant",
        "query": query[:300],
        "host": safe_host(result.url),
        "title": (result.title or "")[:300],
        "snippet": _truncate(result.snippet or "", max_chars),
        "source": getattr(result, "backend", "") or getattr(result, "source", "") or "",
    }


class ShadowRecord:
    """One shadow observation. Built from dataclass fields via __init__."""

    __slots__ = (
        "actual_route",
        "backend",
        "browser_attempted",
        "browser_success",
        "content_length",
        "error_code",
        "input_tokens",
        "jev_call_id",
        "jev_confidence",
        "jev_decision",
        "jev_error",
        "jev_latency_ms",
        "jev_probability",
        "jev_provider",
        "jev_question",
        "model_requested",
        "model_resolved",
        "operation",
        "output_tokens",
        "position",
        "rule_decision",
        "rule_reason",
        "run_id",
        "schema_version",
        "search_provider",
        "timestamp",
        "trace_id",
    )

    def __init__(self, **kwargs: Any) -> None:
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k))

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


class JevShadowRecorder:
    """Bounded in-memory recorder + metrics. Thread-safe.

    This is intentionally simple: a deque of recent records plus counters.
    It is NOT a durable store and NOT an observability replacement.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: deque[ShadowRecord] = deque(maxlen=_MAX_RECORDS)
        self._latencies: list[float] = []
        # agreement buckets for fetch escalation: (rule, jev)
        self._agree_yes = 0
        self._agree_no = 0
        self._disagree_rule_no_jev_yes = 0
        self._disagree_rule_yes_jev_no = 0
        self._calls = 0
        self._success = 0
        self._failure = 0
        self._timeout = 0

    def record(
        self,
        *,
        operation: str,
        jev_question: str,
        decision: JevDecision | None,
        rule_decision: bool | None,
        rule_reason: str | None,
        backend: str | None = None,
        content_length: int | None = None,
        actual_route: str | None = None,
        browser_attempted: bool | None = None,
        browser_success: bool | None = None,
        error_code: str | None = None,
        position: int | None = None,
        search_provider: str | None = None,
        trace_id: str | None = None,
        schema_version: str | None = None,
        run_id: str | None = None,
    ) -> None:
        rec = ShadowRecord(
            timestamp=time.time(),
            trace_id=trace_id or stable_hash(str(time.time()), operation),
            operation=operation,
            jev_question=jev_question,
            jev_decision=decision.decision if decision else None,
            jev_probability=decision.probability_yes if decision else None,
            jev_confidence=decision.confidence if decision else None,
            jev_latency_ms=decision.latency_ms if decision else 0.0,
            jev_provider=decision.provider if decision else None,
            jev_error=decision.error if decision else None,
            input_tokens=getattr(decision, "input_tokens", None) if decision else None,
            output_tokens=getattr(decision, "output_tokens", None) if decision else None,
            jev_call_id=getattr(decision, "jev_call_id", None) if decision else None,
            model_requested=getattr(decision, "model_requested", None) if decision else None,
            model_resolved=getattr(decision, "model_resolved", None) if decision else None,
            run_id=run_id or PROCESS_RUN_ID,
            rule_decision=rule_decision,
            rule_reason=rule_reason,
            backend=backend,
            content_length=content_length,
            actual_route=actual_route,
            browser_attempted=browser_attempted,
            browser_success=browser_success,
            error_code=error_code,
            position=position,
            search_provider=search_provider,
            schema_version=schema_version,
        )
        with self._lock:
            self._records.append(rec)
            self._calls += 1
            if decision is None or decision.error:
                self._failure += 1
            else:
                self._success += 1
                self._latencies.append(decision.latency_ms)
                if len(self._latencies) > 2000:
                    self._latencies = self._latencies[-2000:]
            # Agreement tracking only makes sense for fetch escalation.
            if rule_decision is not None and decision is not None and not decision.error:
                if rule_decision and decision.decision:
                    self._agree_yes += 1
                elif not rule_decision and not decision.decision:
                    self._agree_no += 1
                elif rule_decision and not decision.decision:
                    self._disagree_rule_yes_jev_no += 1
                else:
                    self._disagree_rule_no_jev_yes += 1
        # Durable write (best-effort, off the lock). Sensitive fields are
        # already stripped by build_fetch_state / build_search_state.
        try:
            append_record(rec.to_dict())
        except Exception:  # pragma: no cover - persistence must not break shadow
            log.debug("Jev SQLite append failed; in-memory record kept")

    def note_timeout(self) -> None:
        with self._lock:
            self._timeout += 1

    def summary(self) -> dict[str, Any]:
        with self._lock:
            lat = sorted(self._latencies)
            total_agree = self._agree_yes + self._agree_no
            total_disagree = self._disagree_rule_no_jev_yes + self._disagree_rule_yes_jev_no
            total = total_agree + total_disagree
            return {
                "calls": self._calls,
                "success": self._success,
                "failure": self._failure,
                "timeout": self._timeout,
                "latency_p50_ms": _pct(lat, 0.5),
                "latency_p95_ms": _pct(lat, 0.95),
                "fetch_agree_yes": self._agree_yes,
                "fetch_agree_no": self._agree_no,
                "fetch_disagree_rule_no_jev_yes": self._disagree_rule_no_jev_yes,
                "fetch_disagree_rule_yes_jev_no": self._disagree_rule_yes_jev_no,
                "fetch_agreement_rate": round(total_agree / total, 4) if total else None,
                "recent_records": [r.to_dict() for r in list(self._records)[-20:]],
            }

    def reset(self) -> None:
        with self._lock:
            self._records.clear()
            self._latencies.clear()
            self._agree_yes = self._agree_no = 0
            self._disagree_rule_no_jev_yes = self._disagree_rule_yes_jev_no = 0
            self._calls = self._success = self._failure = self._timeout = 0


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    idx = min(len(values) - 1, int(len(values) * p))
    return round(values[idx], 2)


# Module-level singleton. Tests can call reset_for_tests().
_recorder = JevShadowRecorder()


def get_recorder() -> JevShadowRecorder:
    return _recorder


def reset_for_tests() -> None:
    _recorder.reset()


async def maybe_record_fetch(
    client: JevClient,
    *,
    response: FetchResponse,
    rule_decision: FetchEscalationDecision | None,
    backend: str,
    actual_route: str,
    browser_attempted: bool,
    browser_success: bool,
    max_state_chars: int,
    trace_id: str | None = None,
    run_id: str | None = None,
) -> None:
    """Best-effort shadow call after a fetch completes. Never raises.

    Uses ask_many so needs_escalation + result_usable are answered in one
    TypeSafe system_one call (one RTT, one state payload).
    Noop client: nothing is recorded (no fake decisions pollute the DB).
    """
    if getattr(client, "name", "") in ("noop", ""):
        return
    try:
        trace_id = trace_id or stable_hash(str(time.time()), "fetch")
        state = build_fetch_state(response, rule_decision, max_state_chars)
        rule_bool = bool(rule_decision and rule_decision.escalate)
        rule_reason = rule_decision.reason_code.value if rule_decision and rule_decision.reason_code else None
        questions = ["needs_escalation", "result_usable"]
        try:
            answers = await client.ask_many(questions, state)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("Jev ask_many failed: %s", exc)
            answers = {}
        for q in questions:
            decision = answers.get(q)
            _recorder.record(
                operation="fetch",
                jev_question=q,
                decision=decision,
                rule_decision=rule_bool if q == "needs_escalation" else None,
                rule_reason=rule_reason if q == "needs_escalation" else None,
                backend=backend,
                content_length=state.get("content_length"),
                actual_route=actual_route,
                browser_attempted=browser_attempted,
                browser_success=browser_success,
                trace_id=trace_id,
                run_id=run_id,
                schema_version=JEV_DECISION_SCHEMA_VERSION,
            )
    except Exception:  # pragma: no cover - absolute safety net
        log.exception("Jev shadow fetch recording failed; swallowed")


async def maybe_record_search(
    client: JevClient,
    *,
    query: str,
    results: list[SearchResult],
    max_results: int,
    max_state_chars: int,
    trace_id: str | None = None,
    run_id: str | None = None,
) -> None:
    """Best-effort shadow call for top-N search results. Never raises.

    Each result has its own state (title/snippet/host), so we issue one
    ask_many(question) per result — but it runs fire-and-forget and never
    blocks the MCP response. A single batched system_one call over all N
    results would require a shared-state schema; deferred until TypeSafe
    cookbook guidance is available.
    Noop client: nothing is recorded.
    """
    if getattr(client, "name", "") in ("noop", ""):
        return
    try:
        trace_id = trace_id or stable_hash(str(time.time()), "search", query[:64])
        for pos, result in enumerate(results[:max_results], start=1):
            state = build_search_state(query, result, max_state_chars)
            try:
                answers = await client.ask_many(["result_relevant"], state)
                decision = answers.get("result_relevant")
            except Exception as exc:  # pragma: no cover
                log.debug("Jev result_relevant failed: %s", exc)
                decision = None
            _recorder.record(
                operation="search",
                jev_question="result_relevant",
                decision=decision,
                rule_decision=None,
                rule_reason=None,
                position=pos,
                search_provider=getattr(result, "backend", "") or None,
                trace_id=trace_id,
                run_id=run_id,
                schema_version=JEV_DECISION_SCHEMA_VERSION,
            )
    except Exception:  # pragma: no cover
        log.exception("Jev shadow search recording failed; swallowed")
