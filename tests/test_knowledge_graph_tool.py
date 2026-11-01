"""web_knowledge_graph: contract tests for the 12th MCP tool.

Three things must hold, and each was a real failure during development:

1. **text mode works** - the straightforward path
2. **exactly one input is required** - a silently empty graph is worse than an error
3. **the url branch goes through fetch_service, not the bare fetcher** - calling
   `fetcher.fetch` directly bypassed the SSRF guard, provider selection, TLS
   impersonation, browser escalation and recovery classification, and returned empty
   content on pages `web_fetch` reads fine. That is the "looks implemented, does not
   work" failure this project has spent releases removing, so it gets a test.

Also pinned: Fetcher.fetch takes no `timeout` argument. Passing one raised TypeError
at call time, which only a live invocation surfaced.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from webscout_mcp.fetcher import Fetcher
from webscout_mcp.server import create_server


def _payload(result) -> dict:
    """MCP 1.x returns (content, structured); 2.x returns CallToolResult."""
    obj = result[0] if isinstance(result, tuple) else result
    content = getattr(obj, "content", obj)
    block = content[0] if isinstance(content, list) else content
    return json.loads(getattr(block, "text", str(block)))


def _call(name: str, args: dict) -> dict:
    async def go():
        server = create_server()
        return await server.call_tool(name, args)

    return _payload(asyncio.run(go()))


# --- registration -----------------------------------------------------


def test_tool_is_registered_with_its_siblings():
    async def go():
        server = create_server()
        return await server.list_tools()

    tools = asyncio.run(go())
    names = {t.name for t in tools}
    assert "web_knowledge_graph" in names
    assert len(names) == 13, f"tool count changed: {sorted(names)}"


def test_tool_declares_its_limits_in_the_docstring():
    """The extraction is rule-based; the description must not oversell it."""

    async def go():
        server = create_server()
        return await server.list_tools()

    tools = asyncio.run(go())
    tool = next(t for t in tools if t.name == "web_knowledge_graph")
    desc = (tool.description or "").lower()
    assert "co_occurs_with" in desc or "co-occurrence" in desc, "relationship limitation must be stated"
    assert "unknown" in desc, "the honest type fallback must be stated"


# --- text mode --------------------------------------------------------


def test_text_mode_builds_a_graph():
    out = _call(
        "web_knowledge_graph",
        {
            "text": (
                "Apple Inc. is a technology company. Tim Cook is the CEO of Apple Inc. "
                "Microsoft Corporation competes with Apple Inc."
            )
        },
    )
    assert out["source"] == "text"
    assert out["stats"]["entity_count"] >= 2
    names = {e["name"] for e in out["entities"]}
    assert "Apple Inc" in names
    assert "Microsoft Corporation" in names


def test_every_entity_carries_an_honest_type():
    """Types are rule-based. 'unknown' is required rather than a wrong guess."""
    out = _call(
        "web_knowledge_graph",
        {"text": "Python was created by Guido. Django is a framework. Apple Inc. is a company."},
    )
    allowed = {"person", "organization", "location", "technology", "date", "number", "unknown"}
    for entity in out["entities"]:
        assert entity["type"] in allowed, f"unexpected type {entity['type']!r}"


def test_relationships_are_labelled_as_cooccurrence():
    out = _call(
        "web_knowledge_graph",
        {"text": "Apple Inc. makes phones. Apple Inc. employs Tim Cook. Tim Cook leads Apple Inc."},
    )
    for rel in out["relationships"]:
        assert rel["type"] == "co_occurs_with", "relationship type must stay honest until semantic parsing exists"


def test_notes_explain_the_limitations():
    out = _call("web_knowledge_graph", {"text": "Apple Inc. is a company. Apple Inc. is large."})
    notes = " ".join(out.get("notes", [])).lower()
    assert "co-occurrence" in notes
    assert "unknown" in notes


def test_max_entities_caps_the_output():
    text = " ".join(f"Company{i} Inc. is a business." for i in range(30))
    out = _call("web_knowledge_graph", {"text": text, "max_entities": 5})
    assert len(out["entities"]) <= 5


def test_centrality_can_be_disabled():
    out = _call(
        "web_knowledge_graph",
        {"text": "Apple Inc. is big. Apple Inc. is old.", "include_centrality": False},
    )
    assert "top_entities_by_centrality" not in out


# --- input validation -------------------------------------------------


def test_no_input_is_an_explicit_error():
    out = _call("web_knowledge_graph", {})
    assert "error" in out
    assert "url" in out["error"] and "text" in out["error"]


def test_empty_text_is_treated_as_missing():
    out = _call("web_knowledge_graph", {"text": ""})
    assert "error" in out


# --- the url branch must use the pipeline -----------------------------


def test_url_branch_uses_fetch_service_not_the_bare_fetcher():
    """Pins the fix: the bare fetcher skipped SSRF, providers, TLS, browser, recovery."""
    src = inspect.getsource(create_server)
    # locate the tool body
    idx = src.find("async def web_knowledge_graph")
    assert idx != -1
    body = src[idx:]
    url_branch = body[: body.find("# --- end") if "# --- end" in body else len(body)]
    assert "fetch_service.fetch(" in body, "url branch must go through fetch_service"
    assert "fetcher.fetch(" not in url_branch, (
        "calling Fetcher.fetch directly bypasses the pipeline and returns empty content"
    )


def test_fetcher_fetch_still_takes_no_timeout():
    """The signature the tool must match. It passed timeout= and got a TypeError."""
    params = inspect.signature(Fetcher.fetch).parameters
    assert "timeout" not in params, "if this changes, the tool's call may be simplified"


def test_url_failure_reports_recovery_diagnosis():
    """A blocked fetch must name why, not return an empty graph.

    On this machine DNS returns a fake-IP range so the SSRF guard rejects public
    hosts, which conveniently exercises the failure branch.
    """
    out = _call("web_knowledge_graph", {"url": "https://docs.python.org/3/"})
    if "error" in out:
        assert "recovery_reason" in out or "recovery_outcome" in out, "a failed fetch must explain itself"
