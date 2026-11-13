"""The activity section must survive a real failure.

## The bug this pins

`provider_activity` summed every value in each provider's stats dict:

    total = sum(sum(int(v) for v in stats.values()) ...)

When the per-provider record gained `last_failure_kind` (a string), `int('provider')` raised
`ValueError` inside a `try/except` that converted the whole section into `{"error": ...}`.

Every existing test passed, because they all ran before any search - so the stats dicts held
only integers. The failure needed a real recorded failure to appear, which is precisely the
situation the section exists to report.

These tests drive a search first, for that reason.
"""

from __future__ import annotations

import json

import pytest


def _payload(result) -> dict:
    obj = result[0] if isinstance(result, tuple) else result
    content = getattr(obj, "content", obj)
    block = content[0] if isinstance(content, list) else content
    return json.loads(getattr(block, "text", str(block)))


async def _practise_search(server) -> None:
    """Drive one search. Its outcome does not matter; recording one does."""
    await server.call_tool("web_search", {"query": "python", "max_results": 1})


@pytest.mark.asyncio
async def test_activity_survives_a_recorded_failure():
    """The regression: a string field in the stats dict broke the sum."""
    from webscout_mcp.server import create_server

    server = create_server()
    await _practise_search(server)
    data = _payload(await server.call_tool("search_health", {}))

    activity = data.get("provider_activity")
    assert activity is not None, "the section disappeared entirely"
    assert "error" not in activity, f"the section was replaced by an error object: {activity.get('error')}"
    assert activity.get("outcome_events") is not None, "outcome_events became null"


@pytest.mark.asyncio
async def test_outcome_events_counts_only_the_counters():
    """`last_failure_kind` is descriptive and must not be summed."""
    from webscout_mcp.server import create_server

    server = create_server()
    await _practise_search(server)
    activity = _payload(await server.call_tool("search_health", {}))["provider_activity"]

    assert isinstance(activity["outcome_events"], int)
    # One search touching two providers produces exactly two outcome events.
    assert activity["outcome_events"] >= 2


@pytest.mark.asyncio
async def test_per_provider_records_carry_a_reason_after_failure():
    """The whole point: a failed provider says more than "error"."""
    from webscout_mcp.server import create_server

    server = create_server()
    await _practise_search(server)
    per_provider = _payload(await server.call_tool("search_health", {}))["provider_activity"]["per_provider"]

    failed = {n: s for n, s in per_provider.items() if s.get("error")}
    assert failed, "the search was expected to fail on this machine and record a reason"
    for name, stats in failed.items():
        assert "last_failure_kind" in stats, (
            f"{name} recorded an error with no kind; the decision detail is being dropped"
        )
