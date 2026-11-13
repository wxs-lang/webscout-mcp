"""search_health must report what the live path actually observed.

## The gap this closes

`SearchService` records per-provider outcomes and recovery actions on every request. The
health report showed `total_requests: 0` / `observed: false` because `get_health_report()`
reads a *separate* counter set in `search_health.py`. Measured after two searches:

    service kept:    {'bing': {'error': 2}, 'duckduckgo': {'error': 2}}
                     {'TRY_NEXT_PROVIDER': 4, 'RETURN_ERROR': 2}
    report showed:   total_requests 0, observed false

Two parallel accountings, and the one wired into the live path was the one nobody reported.

## Why it matters beyond tidiness

On CI, 190 searches were all served by bing. Without these counts there was no way to
distinguish "fallback never needed" from "fallback never fired" - and the second would be a
serious defect in a headline capability. After this change the answer is one field away.
"""

from __future__ import annotations

import json

import pytest


def _payload(result) -> dict:
    obj = result[0] if isinstance(result, tuple) else result
    content = getattr(obj, "content", obj)
    block = content[0] if isinstance(content, list) else content
    return json.loads(getattr(block, "text", str(block)))


@pytest.mark.asyncio
async def test_health_reports_provider_activity():
    from webscout_mcp.server import create_server

    server = create_server()
    data = _payload(await server.call_tool("search_health", {}))
    assert "provider_activity" in data, "the report must expose what the live path observed; it previously did not"


@pytest.mark.asyncio
async def test_activity_names_the_providers_it_contacted():
    """The field that answers "was a second backend ever reached"."""
    from webscout_mcp.server import create_server

    server = create_server()
    # Drive at least one search so the counters move. The result does not matter here -
    # a failure still records an outcome, which is the point.
    await server.call_tool("web_search", {"query": "python", "max_results": 1})

    data = _payload(await server.call_tool("search_health", {}))
    activity = data["provider_activity"]
    assert "providers_contacted" in activity
    assert "per_provider" in activity
    assert "recovery_actions" in activity
    assert isinstance(activity["providers_contacted"], list)


@pytest.mark.asyncio
async def test_an_empty_activity_map_says_why():
    """An empty map must not read as "backends unused"."""
    from webscout_mcp.server import create_server

    server = create_server()
    data = _payload(await server.call_tool("search_health", {}))
    activity = data.get("provider_activity", {})
    assert activity.get("note"), (
        "an empty outcome map needs a note explaining it means 'no search yet', not 'these backends are unused'"
    )


@pytest.mark.asyncio
async def test_activity_does_not_break_the_existing_report():
    """The pre-existing sections must survive the addition."""
    from webscout_mcp.server import create_server

    server = create_server()
    data = _payload(await server.call_tool("search_health", {}))
    for key in ("active_search_path", "search_service", "provider_registry"):
        assert key in data, f"{key} disappeared from the report"
