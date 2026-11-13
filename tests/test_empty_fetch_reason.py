"""An empty fetch must say why, in every tool that reports one.

## Measured

`"Failed to fetch page content"` appeared nine times in server.py, and the tools disagreed on
whether to explain:

    broken_links (fetch_error branch)   {"error": ..., "reason": fetch_error}
    broken_links (empty-html branch)    {"error": ...}                  <- no reason
    web_knowledge_graph                 carries a reason
    web_compare_sites                   carries a reason
    metadata_extract                    {"error": ...}                  <- no reason
    content_quality                     {"error": ...}                  <- no reason

The `broken_links` case is the clearest: four lines apart, the same function answers the same
question two different ways.

## Why it matters

"Failed to fetch page content" is the same message for a 403, a DNS failure and a login wall.
A caller has to respond differently to each, and the response object already held the answer -
`status_code`, `error`, `recovery_outcome`. `metadata_extract` reads that object on the very
next line to get `final_url`.

## What these tests pin

The reason is derived from what the response carries, never invented, and an object with
nothing to say produces a sentence that says exactly that.
"""

from __future__ import annotations

import ast

import pytest

from webscout_mcp.server import _empty_fetch_reason


class _Response:
    def __init__(self, **fields: object) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


def test_a_status_is_reported():
    reason = _empty_fetch_reason(_Response(status_code=403))
    assert "403" in reason


def test_an_error_text_is_reported():
    reason = _empty_fetch_reason(_Response(error="DNS lookups failed"))
    assert "DNS lookups failed" in reason


def test_a_recovery_outcome_is_reported():
    reason = _empty_fetch_reason(_Response(status_code=200, recovery_outcome="terminal"))
    assert "terminal" in reason


def test_several_facts_are_joined():
    reason = _empty_fetch_reason(_Response(status_code=503, error="Service Unavailable"))
    assert "503" in reason and "Service Unavailable" in reason


def test_an_uninformative_response_says_so():
    """Silence must be named, not left as an empty string."""
    reason = _empty_fetch_reason(_Response())
    assert reason
    assert "empty" in reason.lower()


def test_an_ok_extraction_status_is_not_reported_as_a_problem():
    """`extraction_status == "ok"` on an empty body is not a reason."""
    reason = _empty_fetch_reason(_Response(status_code=200, extraction_status="ok"))
    assert "extraction=ok" not in reason


def _dict_literals_with_error(source: str) -> list[dict]:
    """Every dict literal in `source` that carries the fetch-failure message."""
    out: list[dict] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
        values = [v.value for v in node.values if isinstance(v, ast.Constant)]
        if "error" not in keys:
            continue
        if not any(isinstance(v, str) and "Failed to fetch page content" in v for v in values):
            continue
        # Any of these tells the caller something about why. Requiring the literal key
        # `reason` was too narrow: two dicts already carried `recovery_reason` and
        # `recovery_outcome`, which answer the same question under a different name.
        explanatory = {"reason", "recovery_reason", "recovery_outcome", "error_code"}
        out.append(
            {
                "keys": keys,
                "has_reason_key": bool(explanatory & set(keys)),
                "line": node.lineno,
            }
        )
    return out


@pytest.mark.parametrize(
    "tool_name",
    ["metadata_extract", "content_quality", "broken_links"],
)
def test_the_tool_reports_a_reason_when_the_body_is_empty(tool_name):
    """Structural: the failure dict must carry a field that explains it.

    Parsed rather than line-matched: the first version of this test flagged the first line of
    a multi-line dict as "bare" when the reason sat on the next line. The code was right and
    the check was wrong.
    """
    import inspect

    from webscout_mcp.server import create_server

    source = inspect.getsource(create_server)
    start = source.find(f"async def {tool_name}")
    assert start != -1, tool_name
    end = source.find("@mcp.tool", start + 1)
    body = source[start : end if end != -1 else len(source)]

    failures = _dict_literals_with_error(body)
    assert failures, f"{tool_name}: expected at least one fetch-failure dict in the source"
    bare = [f for f in failures if not f["has_reason_key"]]
    assert not bare, f"{tool_name} returns a failure dict with no reason key: {bare}"


def test_no_tool_returns_a_bare_fetch_failure():
    """The end-state assertion across the whole server.

    Every dict carrying this message must also carry an explanatory key. The helper's own
    docstring mentions the message and is not a dict, so it is not counted.
    """
    import inspect

    from webscout_mcp.server import create_server

    source = inspect.getsource(create_server)
    failures = _dict_literals_with_error(source)
    assert failures, "expected fetch-failure dicts in server.py"
    bare = [f for f in failures if not f["has_reason_key"]]
    assert not bare, f"failure dicts without a reason key at lines {[f['line'] for f in bare]}"
