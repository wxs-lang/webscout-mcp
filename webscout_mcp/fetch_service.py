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

from dataclasses import dataclass, field
from typing import Any

from .fetch_escalation import FetchEscalationDecision, should_escalate_to_browser
from .fetch_provider import FetchProvider, FetchRequest, FetchResponse
from .logging_config import get_logger
from .normalization import fetch_response_to_web_result
from .observability import record_escalation, record_fetch_attempt
from .provider_registry import ProviderRegistry
from .provider_router import ProviderCapability, ProviderRouter
from .web_result import WebResult

log = get_logger(__name__)


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
    primary_provider: str = ""
    browser_provider: str | None = None
    browser_attempted: bool = False
    browser_success: bool = False
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
    ):
        self.registry = registry
        self.router: ProviderRouter | None = registry.router
        # Fallback: if the registry has no FETCH provider yet (e.g. tests),
        # allow an explicit one. In production the HTTPFetchProvider is
        # always registered.
        self._fallback_http = fallback_http_provider

    async def fetch(self, request: FetchRequest) -> FetchRouteResult:
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
            except Exception:  # pragma: no cover
                log.exception("observability record fast fetch failed")

        # 3) Escalation decision.
        decision = should_escalate_to_browser(primary)
        final = primary
        browser_provider_name: str | None = None
        browser_attempted = False
        browser_success = False

        if decision.escalate:
            route_trace.append(
                {
                    "action": "escalate",
                    "reason": decision.reason_code.value if decision.reason_code else "unknown",
                }
            )
            try:
                record_escalation(decision.reason_code.value if decision.reason_code else "unknown")
            except Exception:  # pragma: no cover
                log.exception("observability record_escalation failed")

            browser_name = self.registry.select(ProviderCapability.BROWSER)
            browser_provider = self.registry.get(browser_name) if browser_name else None
            if browser_provider is not None:
                browser_attempted = True
                browser_provider_name = browser_name
                try:
                    browser_resp = await browser_provider.fetch(request)
                    route_trace.append(
                        {
                            "capability": "browser",
                            "provider": browser_name,
                            "result": "success" if browser_resp.is_success and browser_resp.content else "failure",
                        }
                    )
                    if self.router is not None and browser_name:
                        self.router.record_result(
                            browser_name,
                            bool(browser_resp.is_success and browser_resp.content),
                            browser_resp.latency_ms,
                            error_type=_router_error_type(browser_resp),
                        )
                    if browser_resp.is_success and browser_resp.content:
                        # Keep the fast response as primary; prefer browser content.
                        final = browser_resp
                        browser_success = True
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("Browser escalation failed: %s", exc)
                    route_trace.append(
                        {
                            "capability": "browser",
                            "provider": browser_name,
                            "result": "failure",
                            "error": type(exc).__name__,
                        }
                    )
                    # final stays = primary (fast result preserved).

        # 4) Normalize to WebResult as the internal unified result.
        web_result = fetch_response_to_web_result(final)

        return FetchRouteResult(
            primary_response=primary,
            final_response=final,
            web_result=web_result,
            escalation_decision=decision if decision.escalate else None,
            primary_provider=primary_name,
            browser_provider=browser_provider_name,
            browser_attempted=browser_attempted,
            browser_success=browser_success,
            route_trace=route_trace,
            used_legacy_fast_path=used_legacy,
        )


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
