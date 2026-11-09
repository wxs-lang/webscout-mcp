"""The MCP payload must say what recovery decided.

Without these fields a challenge page is indistinguishable from a good fetch:

    {"status_code": 200, "error": null, "error_code": null, "extraction_status": "ok"}

while the pipeline had concluded "CHALLENGE, need a browser, none registered". That
was only reachable through route_trace on the Python API, so an MCP tool caller could
not see it at all.

`browser_attempted` cannot stand in: it is set only when a browser ran, so its
absence conflates "not needed" with "no backend", which need different fixes.
"""

from __future__ import annotations

import pytest

from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.fetch_service import FetchRouteResult, WebResult
from webscout_mcp.recovery import RecoveryAction, RecoveryDecision, RecoveryReason


def _route(*, reason=None, action=None, outcome=None, browser_attempted=False):
    primary = FetchResponse(
        url="https://example.test/",
        final_url="https://example.test/",
        status_code=200,
        provider="http",
        content="some content",
        content_type="text/html",
    )
    decision = None
    if reason is not None and action is not None:
        decision = RecoveryDecision(reason=reason, action=action, confidence=0.9, details={})
    return FetchRouteResult(
        primary_response=primary,
        final_response=primary,
        web_result=WebResult(url=primary.url),
        recovery_decision=decision,
        recovery_outcome=outcome,
        browser_attempted=browser_attempted,
    )


def test_payload_reports_a_challenge_that_could_not_escalate():
    out = _route(
        reason=RecoveryReason.CHALLENGE,
        action=RecoveryAction.BROWSER,
        outcome="browser_unavailable:fallback_unavailable",
    ).legacy_out(max_chars=4000)

    assert out["recovery_reason"] == "CHALLENGE"
    assert out["recovery_action"] == "BROWSER"
    assert out["recovery_outcome"] == "browser_unavailable:fallback_unavailable"


def test_the_three_outcomes_a_caller_must_distinguish():
    """These need different remedies, so they must not collapse into one signal."""
    unavailable = _route(
        reason=RecoveryReason.CHALLENGE,
        action=RecoveryAction.BROWSER,
        outcome="browser_unavailable:fallback_unavailable",
    ).legacy_out(4000)
    success = _route(
        reason=RecoveryReason.CHALLENGE,
        action=RecoveryAction.BROWSER,
        outcome="browser_success",
        browser_attempted=True,
    ).legacy_out(4000)
    failed = _route(
        reason=RecoveryReason.CHALLENGE,
        action=RecoveryAction.BROWSER,
        outcome="browser_failed:403",
        browser_attempted=True,
    ).legacy_out(4000)

    assert unavailable["recovery_outcome"] == "browser_unavailable:fallback_unavailable"
    assert success["recovery_outcome"] == "browser_success"
    assert failed["recovery_outcome"] == "browser_failed:403"
    assert len({unavailable["recovery_outcome"], success["recovery_outcome"], failed["recovery_outcome"]}) == 3


def test_normal_page_reports_acceptance_not_a_browser_problem():
    out = _route(
        reason=RecoveryReason.COMPLETE_CONTENT,
        action=RecoveryAction.ACCEPT,
        outcome="accepted",
    ).legacy_out(4000)
    assert out["recovery_action"] == "ACCEPT"
    assert out["recovery_outcome"] == "accepted"
    assert "browser_unavailable" not in str(out.get("recovery_outcome"))


def test_truncated_page_reports_continuation():
    out = _route(
        reason=RecoveryReason.OUTPUT_TRUNCATED,
        action=RecoveryAction.CONTINUE_CONTENT,
        outcome="continuation_ready",
    ).legacy_out(4000)
    assert out["recovery_reason"] == "OUTPUT_TRUNCATED"
    assert out["recovery_action"] == "CONTINUE_CONTENT"


def test_fields_are_absent_when_there_was_no_decision():
    """Additive, like extraction_status: present when meaningful, absent otherwise."""
    out = _route().legacy_out(4000)
    assert "recovery_reason" not in out
    assert "recovery_action" not in out
    assert "recovery_outcome" not in out


def test_existing_keys_survive():
    """COMPATIBILITY.md freezes the shape; these are additions, not replacements."""
    out = _route(
        reason=RecoveryReason.CHALLENGE,
        action=RecoveryAction.BROWSER,
        outcome="browser_unavailable:fallback_unavailable",
    ).legacy_out(4000)
    for key in (
        "url",
        "final_url",
        "status_code",
        "title",
        "content",
        "content_type",
        "extracted",
        "extraction_status",
        "cached",
        "error",
        "error_code",
        "retryable",
        "latency_ms",
    ):
        assert key in out, f"{key} disappeared from the payload"
