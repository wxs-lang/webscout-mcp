"""web_rag_context: contract tests for the 13th MCP tool.

Same guard rails as the knowledge-graph tool, for the same reasons - the url branch
must go through fetch_service, and the response must state its own limits rather than
overselling lexical retrieval as semantic search.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from webscout_mcp.server import create_server

DOC = """Static fetching retrieves raw HTML and extracts main content with a readability algorithm. It is fast and cheap. It fails when the content is produced by client-side JavaScript.

Headless browser rendering executes JavaScript before extraction. It costs two to six seconds per page. It reaches content a static request cannot.

Rate limiting returns 429 with a Retry-After header. Blocking returns 403 and does not negotiate."""


def _payload(result) -> dict:
    obj = result[0] if isinstance(result, tuple) else result
    content = getattr(obj, "content", obj)
    block = content[0] if isinstance(content, list) else content
    return json.loads(getattr(block, "text", str(block)))


def _call(args: dict) -> dict:
    async def go():
        server = create_server()
        return await server.call_tool("web_rag_context", args)

    return _payload(asyncio.run(go()))


# --- registration -----------------------------------------------------


def test_tool_is_registered_with_its_siblings():
    async def go():
        server = create_server()
        return await server.list_tools()

    tools = asyncio.run(go())
    names = {t.name for t in tools}
    assert "web_rag_context" in names
    assert len(names) == 17, f"tool count changed: {sorted(names)}"


def test_description_states_that_ranking_is_lexical():
    async def go():
        server = create_server()
        return await server.list_tools()

    tools = asyncio.run(go())
    tool = next(t for t in tools if t.name == "web_rag_context")
    desc = (tool.description or "").lower()
    assert "lexical" in desc or "embedding" in desc, "retrieval limits must be stated"
    assert "compressed_context" in desc, "the field intended for a model must be named"


# --- happy path -------------------------------------------------------


def test_text_mode_returns_ranked_passages():
    out = _call({"text": DOC, "query": "how long does rendering cost", "top_k": 2})
    assert out["source"] == "text"
    assert out["passages"], "expected at least one passage"
    assert len(out["passages"]) <= 2
    assert out["stats"]["chunks_total"] >= 1
    # the answering sentence should be reachable
    assert "seconds" in out["compressed_context"].lower() or any(
        "seconds" in p["text"].lower() for p in out["passages"]
    )


def test_passages_carry_scores_and_ids():
    out = _call({"text": DOC, "query": "retry-after", "top_k": 3})
    for passage in out["passages"]:
        assert "chunk_id" in passage
        assert isinstance(passage["score"], (int, float))
        assert passage["text"].strip()


def test_response_carries_its_own_limitations():
    out = _call({"text": DOC, "query": "browser rendering"})
    notes = " ".join(out.get("notes", [])).lower()
    assert "lexical" in notes or "embedding" in notes
    assert "compressed_context" in notes


def test_confidence_is_bounded():
    out = _call({"text": DOC, "query": "browser rendering"})
    assert 0.0 <= out["confidence"] <= 1.0
    assert 0.0 <= out["retrieval_score"] <= 1.0


def test_top_k_is_respected():
    out = _call({"text": DOC, "query": "browser", "top_k": 1})
    assert len(out["passages"]) <= 1


# --- validation -------------------------------------------------------


def test_no_input_is_an_explicit_error():
    out = _call({})
    assert "error" in out
    assert "url" in out["error"] and "text" in out["error"]


def test_missing_query_is_an_explicit_error():
    """A retrieval tool asked to summarise should say so, not return everything."""
    out = _call({"text": DOC})
    assert "error" in out
    assert "query" in out["error"].lower()


def test_blank_query_is_an_explicit_error():
    out = _call({"text": DOC, "query": "   "})
    assert "error" in out


# --- url branch must use the pipeline ---------------------------------


def test_url_branch_uses_fetch_service():
    """Pins the same fix as the knowledge-graph tool: no bare Fetcher.fetch."""
    src = inspect.getsource(create_server)
    idx = src.find("async def web_rag_context")
    assert idx != -1
    body = src[idx:]
    body = body[: body.find("@mcp.tool()", 1)] if "@mcp.tool()" in body[1:] else body
    assert "fetch_service.fetch(" in body, "url branch must go through fetch_service"
    assert "fetcher.fetch(" not in body, (
        "calling Fetcher.fetch directly bypasses SSRF guard, providers, TLS, browser and recovery"
    )


def test_url_failure_explains_itself():
    """On a blocked fetch the response names a recovery reason, not a bare error."""
    out = _call({"url": "https://docs.python.org/3/", "query": "what is this"})
    if "error" in out:
        assert "recovery_reason" in out or "recovery_outcome" in out


# --- edge cases -------------------------------------------------------


def test_very_short_text_still_works():
    out = _call({"text": "Cats are mammals.", "query": "cats"})
    assert "error" not in out
    assert out["passages"]


def test_chunk_size_is_clamped_so_it_cannot_be_zero():
    out = _call({"text": DOC, "query": "browser", "max_chunk_size": 1})
    assert "error" not in out
    assert out["stats"]["chunks_total"] >= 1
