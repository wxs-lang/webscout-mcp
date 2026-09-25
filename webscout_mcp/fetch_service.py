"""FetchService — unified fetch orchestration via ProviderRegistry.

This is the Phase 2 home for web_fetch routing. It owns:
  * selecting the fast FETCH provider from the registry
  * running the escalation decision
  * selecting the BROWSER provider from the registry when escalation fires
  * merging fast/browser results into a single FetchRouteResult
  * producing a normalized WebResult as the internal result
  * recording observability exactly once per provider call

server.py only constructs the FetchRequest, calls fetch_service.fetch(),
and maps the result back to the legacy JSON shape.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .fetch_escalation import FetchEscalationDecision
from .fetch_provider import FetchProvider, FetchRequest, FetchResponse
from .logging_config import get_logger
from .normalization import fetch_response_to_web_result
from .observability import (
    record_continuation,
    record_escalation,
    record_fetch_attempt,
    record_recovery_classification,
    record_recovery_execution,
)
from .provider_registry import ProviderRegistry
from .provider_router import ProviderCapability, ProviderRouter
from .recovery import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryReason,
    classify_recovery,
    recovery_to_legacy_escalation,
)
from .web_result import WebResult

log = get_logger(__name__)

# Lazy Jev shadow wiring. A broken Jev module must never prevent the main
# system from starting. When JEV_ENABLED=false, make_jev_client returns
# Noop and maybe_record_fetch is a cheap no-op.
_JEV_AVAILABLE = True
try:
    from . import jev_shadow
    from .jev_client import make_jev_client
except Exception:  # pragma: no cover
    _JEV_AVAILABLE = False
    jev_shadow = None  # type: ignore[assignment]
    make_jev_client = None  # type: ignore[assignment]


@dataclass
class FetchRouteResult:
    """Internal result of one web_fetch orchestration.

    ``primary_response`` is always the fast-HTTP result.
    ``final_response`` is the browser result if escalation succeeded,
    otherwise it is the primary response (browser failure never drops the
    fast result).
    """

    primary_response: FetchResponse
    final_response: FetchResponse
    web_result: WebResult
    escalation_decision: FetchEscalationDecision | None = None
    recovery_decision: RecoveryDecision | None = None
    recovery_outcome: str | None = None
    primary_provider: str = ""
    browser_provider: str | None = None
    fallback_provider: str | None = None
    browser_attempted: bool = False
    browser_success: bool = False
    fallback_used: bool = False
    route_trace: list[dict[str, Any]] = field(default_factory=list)
    used_legacy_fast_path: bool = False  # registry had no FETCH provider

    def legacy_out(self, max_chars: int) -> dict[str, Any]:
        """Map the route result back to the pre-Phase-2 web_fetch JSON shape.

        Keeps the external MCP response identical to v1.2.x: fast result's
        to_dict() is the base, browser annotations overlay it when used.
        """
        out = self.primary_response.metadata.get("_legacy_out") or {}
        # Build from the fast response's legacy shape. The HTTPFetchProvider
        # wraps the Fetcher, so FetchResponse is already a thin adapter; we
        # reconstruct the legacy dict from its fields.
        out = {
            "url": self.primary_response.url,
            "final_url": self.primary_response.final_url,
            "status_code": self.primary_response.status_code,
            "title": self.primary_response.title,
            "content": self.primary_response.content,
            "content_type": self.primary_response.content_type,
            "extracted": self.primary_response.extracted,
            "cached": self.primary_response.cached,
            "error": self.primary_response.error,
            "latency_ms": round(self.primary_response.latency_ms, 2),
        }
        if self.escalation_decision is not None:
            out["escalation"] = self.escalation_decision.to_dict()
        # Progressive content delivery (Phase 2.7C). Sourced from the FINAL
        # served response: a browser-escalated response carries no continuation
        # (browser content is not windowed in this phase).
        continuation = _continuation_block(self.final_response.metadata)
        if continuation is not None:
            out["continuation"] = continuation
        if self.browser_attempted:
            out["browser_attempted"] = True
            out["browser_backend"] = self.browser_provider
            out["browser_reason"] = (
                self.escalation_decision.reason_code.value
                if self.escalation_decision and self.escalation_decision.reason_code
                else None
            )
            if self.browser_success:
                out["content"] = self.final_response.content[:max_chars]
                if self.final_response.title:
                    out["title"] = self.final_response.title
                out["extracted"] = True
                out["browser_success"] = True
            else:
                out["browser_success"] = False
                out["browser_error"] = self.final_response.error
        return out


def _continuation_block(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Build the small, backwards-compatible continuation contract from
    window metadata. Returns None for non-windowed / browser responses."""
    if not metadata or "content_total_chars" not in metadata:
        return None
    return {
        "has_more": bool(metadata.get("has_more")),
        "start_char": metadata.get("content_start_char", 0),
        "end_char": metadata.get("content_end_char", 0),
        "next_start_char": metadata.get("next_start_char"),
        "total_chars": metadata.get("content_total_chars", 0),
        "remaining_chars": metadata.get("remaining_chars", 0),
        "served_from_snapshot": bool(metadata.get("served_from_content_snapshot", False)),
        "range_exhausted": bool(metadata.get("range_exhausted", False)),
    }


def _classify_fast_result(resp: FetchResponse) -> str:
    status = resp.status_code or 0
    if resp.error is None and status < 400:
        return "success"
    if status in (401, 403, 451):
        return "forbidden"
    if resp.error and "timeout" in resp.error.lower():
        return "timeout"
    return "failure"


class FetchService:
    """Orchestrates fast fetch + browser escalation via the registry."""

    def __init__(
        self,
        registry: ProviderRegistry,
        fallback_http_provider: FetchProvider | None = None,
        config: Any = None,
    ):
        self.registry = registry
        self.router: ProviderRouter | None = registry.router
        # Fallback: if the registry has no FETCH provider yet (e.g. tests),
        # allow an explicit one. In production the HTTPFetchProvider is
        # always registered.
        self._fallback_http = fallback_http_provider
        self._config = config
        # Jev shadow client. Noop when disabled; errors are swallowed.
        self._jev_client = None
        self._jev_max_state_chars = 6000
        self._pending_jev_tasks: set = set()
        if _JEV_AVAILABLE and config is not None:
            try:
                self._jev_client = make_jev_client(config)
                self._jev_max_state_chars = int(getattr(config, "jev_max_state_chars", 6000))
            except Exception:  # pragma: no cover
                log.debug("Jev client init failed; shadow disabled")
                self._jev_client = None

    async def fetch(self, request: FetchRequest) -> FetchRouteResult:
        _decision_started_at = time.time()
        # 1) Select fast FETCH provider.
        primary_name = self.registry.select(ProviderCapability.FETCH)
        primary_provider: FetchProvider | None = None
        used_legacy = False
        if primary_name:
            primary_provider = self.registry.get(primary_name)  # type: ignore[assignment]
        if primary_provider is None and self._fallback_http is not None:
            primary_provider = self._fallback_http
            primary_name = primary_provider.name
            used_legacy = True

        route_trace: list[dict[str, Any]] = []

        # 2) Fast fetch.
        if primary_provider is None:
            # No fetch provider available at all — return a synthetic failed response.
            primary = FetchResponse(
                url=request.url,
                final_url=request.url,
                status_code=0,
                provider="none",
                error="no fetch provider registered",
            )
            primary_name = "none"
            route_trace.append({"capability": "fetch", "provider": "none", "result": "failure"})
        else:
            primary = await primary_provider.fetch(request)
            route_trace.append(
                {
                    "capability": "fetch",
                    "provider": primary_name,
                    "result": "success" if primary.is_success else "failure",
                }
            )
            # Continuation served from the local content snapshot is NOT a new
            # network fetch: no router result, no fetch-attempt metric, and it
            # must never trigger browser escalation / recovery / Jev.
            continuation_hit = bool(request.start_char > 0 and primary.metadata.get("served_from_content_snapshot"))
            if continuation_hit:
                try:
                    record_continuation("request")
                    record_continuation("snapshot_hit")
                    record_continuation("chunk_served", len(primary.content or ""))
                except Exception:  # pragma: no cover
                    log.exception("observability continuation record failed")
                web_result = fetch_response_to_web_result(primary)
                route_trace.append({"action": "continue_from_snapshot", "provider": primary_name})
                return FetchRouteResult(
                    primary_response=primary,
                    final_response=primary,
                    web_result=web_result,
                    escalation_decision=None,
                    primary_provider=primary_name,
                    browser_provider=None,
                    browser_attempted=False,
                    browser_success=False,
                    route_trace=route_trace,
                    used_legacy_fast_path=used_legacy,
                )
            if request.start_char > 0:
                # Continuation requested but snapshot was missing -> the
                # provider rebuilt it via a real fetch. Count the miss/rebuild;
                # the rest of the normal path applies.
                try:
                    record_continuation("request")
                    record_continuation("snapshot_miss")
                    record_continuation("snapshot_rebuild")
                except Exception:  # pragma: no cover
                    log.exception("observability continuation record failed")
            # Record router result exactly once.
            if self.router is not None and not used_legacy:
                self.router.record_result(
                    primary_name,
                    primary.is_success,
                    primary.latency_ms,
                    error_type=_router_error_type(primary),
                )
            # Observability: exactly once for the fast attempt.
            try:
                record_fetch_attempt(
                    primary_name,
                    result=_classify_fast_result(primary),
                    latency_ms=float(primary.latency_ms or 0.0),
                )
                # A first window carrying progressive-delivery metadata is one
                # served chunk.
                if primary.is_success and "content_total_chars" in primary.metadata:
                    record_continuation("chunk_served", len(primary.content or ""))
            except Exception:  # pragma: no cover
                log.exception("observability record fast fetch failed")

        # 3) Unified recovery classification — the single high-level decision.
        # The low-level browser detector (should_escalate_to_browser) runs
        # exactly once, *inside* classify_recovery. FetchService never calls it
        # directly for production routing, so there is no second parallel judge.
        try:
            recovery = classify_recovery(primary)
        except Exception:  # pragma: no cover - defensive
            log.exception("recovery classification failed; accepting primary")
            recovery = RecoveryDecision(
                reason=RecoveryReason.COMPLETE_CONTENT,
                action=RecoveryAction.ACCEPT,
                confidence=0.0,
                details={"status_code": primary.status_code, "classification_error": True},
            )
        try:
            record_recovery_classification(recovery.reason.value, recovery.action.value)
        except Exception:  # pragma: no cover
            log.exception("observability recovery classification failed")
        route_trace.append(
            {
                "stage": "recovery_classification",
                "reason": recovery.reason.value,
                "action": recovery.action.value,
            }
        )

        action = recovery.action
        # Legacy escalation contract is *derived* from the single recovery
        # decision (no second detector run); only a BROWSER action yields it.
        legacy_escalation = recovery_to_legacy_escalation(recovery)

        final = primary
        browser_provider_name: str | None = None
        browser_attempted = False
        browser_success = False
        fallback_provider_name: str | None = None
        fallback_used = False

        if action is RecoveryAction.BROWSER:
            (
                final,
                browser_provider_name,
                browser_attempted,
                browser_success,
                recovery_outcome,
            ) = await self._execute_browser_recovery(request, primary, recovery, legacy_escalation, route_trace)
        elif action is RecoveryAction.PROVIDER_FALLBACK:
            (
                final,
                fallback_provider_name,
                fallback_used,
                recovery_outcome,
            ) = await self._execute_provider_fallback(request, primary, primary_name, route_trace)
        elif action is RecoveryAction.CONTINUE_CONTENT:
            # The current window + continuation block is already served; the
            # agent decides whether to read the next chunk. Never browser.
            recovery_outcome = "continuation_ready"
        elif action is RecoveryAction.RETRY:
            # Fetcher already owns retries (max_retries, default 3); by the
            # time we classify, retries are exhausted. No second retry loop.
            recovery_outcome = "retry_delegated_to_fetcher"
        elif action is RecoveryAction.RETRY_LATER:
            # 429: never sleep-and-retry inside the MCP request.
            recovery_outcome = "deferred"
        elif action is RecoveryAction.REQUIRE_AUTH:
            recovery_outcome = "user_action_required"
        elif action is RecoveryAction.STOP:
            recovery_outcome = "terminal"
        elif action is RecoveryAction.ACCEPT:
            recovery_outcome = "accepted"
        else:  # RecoveryAction.NONE (AMBIGUOUS)
            recovery_outcome = "no_action"

        try:
            record_recovery_execution(action.value, recovery_outcome)
        except Exception:  # pragma: no cover
            log.exception("observability recovery execution failed")
        route_trace.append({"stage": "recovery_execution", "action": action.value, "outcome": recovery_outcome})

        # 4) Normalize to WebResult as the internal unified result.
        web_result = fetch_response_to_web_result(final)

        # 5) Jev shadow (best-effort, non-blocking). Never changes routing.
        actual_route = "fallback" if fallback_used else ("browser" if browser_success else "fast")
        if self._jev_client is not None and getattr(self._jev_client, "name", "") != "noop":
            try:
                import asyncio

                task = asyncio.create_task(
                    jev_shadow.maybe_record_fetch(
                        self._jev_client,
                        response=primary,
                        rule_decision=legacy_escalation,
                        backend=primary_name,
                        actual_route=actual_route,
                        browser_attempted=browser_attempted,
                        browser_success=browser_success,
                        max_state_chars=self._jev_max_state_chars,
                    )
                )
                self._pending_jev_tasks.add(task)
                task.add_done_callback(self._pending_jev_tasks.discard)
            except Exception:  # pragma: no cover
                log.debug("Jev shadow fire failed", exc_info=True)

        # 6) Decision telemetry (best-effort, never affects routing).
        try:
            from .decision_adapter import record_fetch_decision

            record_fetch_decision(
                request=request,
                primary=primary,
                final=final,
                recovery=recovery,
                recovery_outcome=recovery_outcome,
                primary_provider=primary_name,
                browser_attempted=browser_attempted,
                browser_success=browser_success,
                fallback_used=fallback_used,
                cache_hit=getattr(primary, "from_cache", False),
                snapshot_hit=used_legacy and getattr(request, "start_char", 0) > 0,
                started_at=_decision_started_at,
            )
        except Exception:  # pragma: no cover - telemetry must never break production
            log.debug("fetch decision telemetry failed", exc_info=True)

        return FetchRouteResult(
            primary_response=primary,
            final_response=final,
            web_result=web_result,
            escalation_decision=legacy_escalation,
            recovery_decision=recovery,
            recovery_outcome=recovery_outcome,
            primary_provider=primary_name,
            browser_provider=browser_provider_name,
            fallback_provider=fallback_provider_name,
            browser_attempted=browser_attempted,
            browser_success=browser_success,
            fallback_used=fallback_used,
            route_trace=route_trace,
            used_legacy_fast_path=used_legacy,
        )

    async def _execute_browser_recovery(
        self,
        request: FetchRequest,
        primary: FetchResponse,
        recovery: RecoveryDecision,
        legacy_escalation: FetchEscalationDecision | None,
        route_trace: list[dict[str, Any]],
    ) -> tuple[FetchResponse, str | None, bool, bool, str]:
        """Execute the single active browser recovery. At most one browser
        fetch per web_fetch; the browser response is never re-classified (no
        recovery recursion). Browser failure never drops the fast result."""
        reason_code = (
            legacy_escalation.reason_code.value
            if legacy_escalation and legacy_escalation.reason_code
            else (recovery.details or {}).get("escalation", "unknown")
        )
        route_trace.append({"action": "escalate", "reason": reason_code})
        try:
            record_escalation(reason_code)
        except Exception:  # pragma: no cover
            log.exception("observability record_escalation failed")

        browser_name = self.registry.select(ProviderCapability.BROWSER)
        browser_provider = self.registry.get(browser_name) if browser_name else None
        if browser_provider is None:
            route_trace.append({"capability": "browser", "provider": None, "result": "unavailable"})
            return primary, None, False, False, "browser_unavailable"

        try:
            browser_resp = await browser_provider.fetch(request)
            ok = bool(browser_resp.is_success and browser_resp.content)
            route_trace.append(
                {
                    "capability": "browser",
                    "provider": browser_name,
                    "result": "success" if ok else "failure",
                }
            )
            if self.router is not None and browser_name:
                self.router.record_result(
                    browser_name,
                    ok,
                    browser_resp.latency_ms,
                    error_type=_router_error_type(browser_resp),
                )
            if ok:
                return browser_resp, browser_name, True, True, "browser_success"
            return primary, browser_name, True, False, "browser_failed"
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Browser recovery failed: %s", exc)
            route_trace.append(
                {
                    "capability": "browser",
                    "provider": browser_name,
                    "result": "failure",
                    "error": type(exc).__name__,
                }
            )
            # final stays = primary (fast result preserved).
            return primary, browser_name, True, False, "browser_failed"

    async def _execute_provider_fallback(
        self,
        request: FetchRequest,
        primary: FetchResponse,
        primary_name: str,
        route_trace: list[dict[str, Any]],
    ) -> tuple[FetchResponse, str | None, bool, str]:
        """Try at most ONE alternate FETCH provider. Never uses the browser as
        a FETCH fallback; a failed alternate is terminal (no third provider)."""
        exclude = [primary_name] if primary_name and primary_name != "none" else None
        alt_name = self.registry.select(ProviderCapability.FETCH, exclude=exclude)
        alt_provider = self.registry.get(alt_name) if alt_name else None
        if alt_provider is None or alt_name == primary_name:
            route_trace.append({"stage": "provider_fallback", "result": "unavailable"})
            return primary, None, False, "fallback_unavailable"

        route_trace.append({"stage": "provider_fallback", "provider": alt_name})
        try:
            alt_resp = await alt_provider.fetch(request)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("Provider fallback failed: %s", exc)
            route_trace.append(
                {
                    "capability": "fetch",
                    "provider": alt_name,
                    "result": "failure",
                    "error": type(exc).__name__,
                }
            )
            return primary, alt_name, False, "fallback_failed"

        ok = bool(alt_resp.is_success and alt_resp.content)
        route_trace.append({"capability": "fetch", "provider": alt_name, "result": "success" if ok else "failure"})
        if self.router is not None and alt_name:
            self.router.record_result(
                alt_name,
                ok,
                alt_resp.latency_ms,
                error_type=_router_error_type(alt_resp),
            )
        try:
            record_fetch_attempt(
                alt_name,
                result=_classify_fast_result(alt_resp),
                latency_ms=float(alt_resp.latency_ms or 0.0),
            )
        except Exception:  # pragma: no cover
            log.exception("observability record fallback fetch failed")
        if ok:
            return alt_resp, alt_name, True, "fallback_success"
        return primary, alt_name, False, "fallback_failed"

    async def flush_pending_jev_tasks(self, timeout: float | None = None) -> None:
        """Best-effort wait for in-flight Jev shadow tasks at shutdown.

        Default timeout is JEV_TIMEOUT_MS/1000 + 2.0s buffer so a shadow
        request in flight has a fair chance to finish, with a hard upper
        bound so shutdown never hangs."""
        if not self._pending_jev_tasks:
            if self._jev_client is not None:
                try:
                    await self._jev_client.aclose()
                except Exception:  # pragma: no cover
                    log.debug("Jev client close failed", exc_info=True)
            return
        import asyncio

        if timeout is None:
            cfg_timeout_ms = getattr(self._config, "jev_timeout_ms", 8000) if self._config else 8000
            timeout = float(cfg_timeout_ms) / 1000.0 + 2.0
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._pending_jev_tasks, return_exceptions=True),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Exception):
            pass
        self._pending_jev_tasks.clear()
        if self._jev_client is not None:
            try:
                await self._jev_client.aclose()
            except Exception:  # pragma: no cover
                log.debug("Jev client close failed", exc_info=True)


def _router_error_type(resp: FetchResponse) -> str | None:
    if resp.is_success:
        return None
    status = resp.status_code or 0
    if status == 429:
        return "rate_limited"
    if status == 403:
        return "forbidden"
    if resp.error and "timeout" in resp.error.lower():
        return "timeout"
    if resp.error and any(k in resp.error.lower() for k in ("dns", "connect", "ssl")):
        return "connection_error"
    return "unknown"
