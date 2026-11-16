"""web_fetch's docstring promises the CALL returns at most max_chars characters.

Only `content` used to be capped, so a max_chars=500 request returned a
1,294-character envelope — 500 of content plus 794 of metadata and whitespace.
For an agent budgeting context, a contract about call size that only applies to
one field is not a contract.

These tests pin the corrected behaviour and, just as importantly, pin what
happens when the request is impossible, so a future change neither regresses the
guarantee nor silently fabricates compliance.

No network: the fetch route is stubbed with a fixed large body.
"""

from __future__ import annotations

import json

import pytest


class _Route:
    """Stands in for the fetch service result."""

    def __init__(self, body: str) -> None:
        self._body = body

    def legacy_out(self, max_chars: int) -> dict:
        body = self._body[:max_chars]
        return {
            "url": "https://example.test/page",
            "final_url": "https://example.test/page",
            "status_code": 200,
            "title": "A test page",
            "content": body,
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
            "continuation": {
                "has_more": len(self._body) > len(body),
                "next_start_char": len(body),
            },
        }


BODY = "word " * 5000  # 25,000 chars


@pytest.fixture
def fetch_tool(monkeypatch):
    """Call the real web_fetch tool body with the fetch service stubbed.

    `fetch_service` is instantiated inside the server factory, so there is no
    module-level object to patch. Patching FetchService.fetch catches every tool
    that fetches, which is also what makes this test independent of how the
    factory wires things.
    """
    import webscout_mcp.server.mcp_server as srv
    from webscout_mcp.orchestration.fetch_service import FetchService

    async def fake_fetch(self, request):
        return _Route(BODY)

    monkeypatch.setattr(FetchService, "fetch", fake_fetch)
    return srv


@pytest.mark.asyncio
async def test_envelope_respects_max_chars(fetch_tool):
    """The whole serialised call must fit the budget, not just `content`."""
    for budget in (1200, 2000, 8000):
        text = await _call(fetch_tool, budget)
        assert len(text) <= budget, (
            f"max_chars={budget} returned {len(text)} chars — the contract is about the call, not the content field"
        )
        json.loads(text)  # still valid JSON at every budget


@pytest.mark.asyncio
async def test_content_is_reduced_not_lost(fetch_tool):
    """Fitting the budget shrinks the window; it must not empty the answer."""
    text = await _call(fetch_tool, 1200)
    payload = json.loads(text)
    assert len(payload["content"]) > 200, "content was over-trimmed to fit"
    assert payload["continuation"]["has_more"] is True
    assert payload["continuation"]["content_truncated_to_fit"] is True


@pytest.mark.asyncio
async def test_impossible_budget_is_reported_not_faked(fetch_tool):
    """Below the metadata floor no trimming can comply; say so with the floor."""
    text = await _call(fetch_tool, 200)
    payload = json.loads(text)
    assert payload["max_chars_exceeded_by_metadata"] is True
    assert payload["envelope_floor_chars"] > 200
    assert payload["chars_returned"] == len(text), "the reported size must be the size actually returned"


@pytest.mark.asyncio
async def test_serialisation_is_compact(fetch_tool):
    """Pretty-printing spent a third of the budget on whitespace."""
    text = await _call(fetch_tool, 8000)
    assert '\n  "' not in text, "envelope is still indented"


async def _call(module, max_chars: int) -> str:
    """Drive web_fetch through the registered server, as a client would."""
    from webscout_mcp.core.config import Config

    server = module.create_server(Config())
    raw = await server.call_tool(
        "web_fetch",
        {
            "url": "https://example.test/page",
            "extract": True,
            "output_format": "markdown",
            "max_chars": max_chars,
            "bypass_cache": False,
            "start_char": 0,
        },
    )
    if isinstance(raw, tuple) and raw and isinstance(raw[0], list):
        raw = raw[0]
    return raw[0].text if isinstance(raw, list) and raw else str(raw)
