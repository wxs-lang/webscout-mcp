"""web_fetch's docstring promises the CALL returns at most max_chars characters.

Only `content` used to be capped, so a max_chars=500 request returned a
1,294-character envelope — 500 of content plus 794 of metadata and whitespace.
For an agent budgeting context, a contract about call size that applies to one
field is not a contract.

These tests exercise ``render_fetch_result`` directly rather than driving a server:
the guarantee lives in that function, and a server-backed test failed on CI for
reasons (browser detection, startup checks) that have nothing to do with the size
contract.
"""

from __future__ import annotations

import json

import pytest

from webscout_mcp.server.mcp_server import render_fetch_result

BODY = "word " * 5000  # 25,000 chars


def _payload(content: str = BODY, has_more: bool = True) -> dict:
    """A fetch result shaped like the real one, without touching the network."""
    return {
        "url": "https://example.test/page",
        "final_url": "https://example.test/page",
        "status_code": 200,
        "title": "A test page",
        "content": content,
        "content_type": "text/markdown",
        "extracted": True,
        "extraction_status": "ok",
        "cached": False,
        "error": "",
        "error_code": "",
        "retryable": False,
        "latency_ms": 12,
        "recovery_reason": "COMPLETE_CONTENT",
        "recovery_action": "ACCEPT",
        "recovery_outcome": "accepted",
        "continuation": {"has_more": has_more, "next_start_char": len(content)},
    }


@pytest.mark.parametrize("budget", [1200, 2000, 8000])
def test_envelope_respects_max_chars(budget):
    """The whole serialised call must fit the budget, not just `content`."""
    text = render_fetch_result(_payload(), budget)
    assert len(text) <= budget, (
        f"max_chars={budget} returned {len(text)} chars — the contract is about the call, not the content field"
    )
    json.loads(text)  # still valid JSON at every budget


def test_content_is_reduced_not_lost():
    """Fitting the budget shrinks the window; it must not empty the answer."""
    text = render_fetch_result(_payload(), 1200)
    payload = json.loads(text)
    assert len(payload["content"]) > 200, "content was over-trimmed to fit"
    assert payload["continuation"]["has_more"] is True
    assert payload["continuation"]["content_truncated_to_fit"] is True
    assert payload["content_available_chars"] == len(BODY)


def test_impossible_budget_is_reported_not_faked():
    """Below the metadata floor no trimming can comply; say so with the floor."""
    text = render_fetch_result(_payload(), 120)
    payload = json.loads(text)
    assert payload["max_chars_exceeded_by_metadata"] is True
    assert payload["envelope_floor_chars"] > 120
    assert payload["chars_returned"] == len(text), "the reported size must be the size actually returned"


def test_serialisation_is_compact():
    """Pretty-printing spent a third of the budget on whitespace."""
    text = render_fetch_result(_payload(), 8000)
    assert '\n  "' not in text, "envelope is still indented"


def test_no_budget_still_returns_valid_json():
    """A generous budget must not distort the payload."""
    text = render_fetch_result(_payload(), 100_000)
    payload = json.loads(text)
    assert payload["content"] == BODY
    assert "content_available_chars" not in payload, "no truncation happened, so the truncation fields should be absent"
