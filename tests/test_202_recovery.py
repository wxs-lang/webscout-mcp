"""202 must not be classed as completed content on the strength of its status code.

## The measured case

amazon.com answers 202 with:

    "JavaScript is disabled. In order to continue, we need to verify that you're not a
     robot. This requires JavaScript."

and before this fix the pipeline reported `error=None`, `outcome=accepted` - a completed
fetch, according to a caller who asked. v1.14.0 fixed that shape for a 200 body carrying a
challenge; 202 had no branch in `classify_recovery`'s documented check order, so it fell
through to COMPLETE_CONTENT.

## What these tests pin

- a 202 with a bot challenge is not accepted
- a 202 with genuine content still is (202 is a legitimate "still building" code)
- the status-only path is gone, so a caller cannot get `accepted` from the number alone
"""

from __future__ import annotations

import pytest

from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.recovery import RecoveryAction, RecoveryReason, classify_recovery

CHALLENGE_202 = (
    "JavaScript is disabled\nIn order to continue, we need to verify that you're not a "
    "robot. This requires JavaScript. Enable JavaScript and then reload this page."
)

REAL_202 = (
    "Static fetching retrieves raw HTML and returns the main content after extraction. "
    + "A headless browser executes JavaScript when the page requires it. " * 30
)


def _response(status: int, content: str, **kwargs) -> FetchResponse:
    return FetchResponse(
        url="https://example.test/",
        final_url="https://example.test/",
        status_code=status,
        provider="http",
        content=content,
        content_type=kwargs.pop("content_type", "text/html"),
        **kwargs,
    )


def test_a_202_bot_challenge_is_not_accepted():
    """The exact amazon.com case: a 202 carrying a robot check."""
    decision = classify_recovery(_response(202, CHALLENGE_202))
    assert decision.action is not RecoveryAction.ACCEPT, f"a 202 challenge must not be accepted; got {decision.action}"


def test_a_202_challenge_is_routed_to_a_browser():
    """A JS challenge is what a browser solves, so escalation is the right action."""
    decision = classify_recovery(_response(202, CHALLENGE_202))
    assert decision.action is RecoveryAction.BROWSER


def test_a_202_with_real_content_is_still_accepted():
    """202 is also a legitimate 'still building' code; real content must not regress."""
    decision = classify_recovery(_response(202, REAL_202))
    assert decision.action is RecoveryAction.ACCEPT
    assert decision.reason is RecoveryReason.COMPLETE_CONTENT


def test_the_202_decision_records_the_grade():
    """A caller must be able to see why it was not accepted."""
    decision = classify_recovery(_response(202, CHALLENGE_202))
    assert "content_grade" in decision.details
    assert decision.details["content_grade"] != "usable"


def test_200_is_unaffected():
    """The fix is scoped to 202; a 200 with real content keeps its behaviour."""
    decision = classify_recovery(_response(200, REAL_202))
    assert decision.action is RecoveryAction.ACCEPT


def test_the_status_range_shortcut_does_not_classify_202():
    """Structural: the old `status < 400 -> success` path must not swallow 202.

    `_classify_fast_result` is telemetry, not the decision - patching it there changed
    nothing observable, which is how the first attempt at this fix was caught.
    """
    import pathlib

    source = pathlib.Path("webscout_mcp/fetch_service.py").read_text(encoding="utf-8")
    start = source.find("def _classify_fast_result")
    end = source.find("class FetchService", start)
    block = source[start:end]
    assert "202" not in block, "the 202 decision belongs in classify_recovery, not in the telemetry classifier"
