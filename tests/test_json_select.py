"""JSON selector extraction and its use in web_monitor.

The reference for the design is changedetection.io, which prefixes the selector with the
language (`json:` for JSONPath, `jq:` for jq) and then reduces the selection to a string
so the ordinary text diff applies. Same split here: extraction knows nothing about
comparison.

`jq` needs a native build, so it is optional. These tests cover both sides of that: the
JSONPath path always, and the jq path via `importorskip` so a plain install still runs
the suite.
"""

from __future__ import annotations

import json

import pytest

from webscout_mcp.json_select import (
    JSON_SELECTOR_PREFIXES,
    SelectError,
    available_languages,
    extract,
    parse_selector,
)

DOC = json.dumps(
    {
        "product": {"name": "Widget", "price": {"amount": 100.0, "currency": "USD"}},
        "stock": {"inStock": True, "count": 5},
        "reviews": [{"author": "a", "rating": 5}, {"author": "b", "rating": 3}],
    }
)


# --- prefix parsing ---------------------------------------------------


def test_prefixes_are_documented():
    assert JSON_SELECTOR_PREFIXES == ("json:", "jq:")


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("json:$.a.b", ("jsonpath", "$.a.b")),
        ("jq:.a.b", ("jq", ".a.b")),
        ("$.a.b", ("jsonpath", "$.a.b")),
        ("  JSON:$.a  ", ("jsonpath", "$.a")),
        ("JQ:.a", ("jq", ".a")),
    ],
)
def test_parse_selector(selector, expected):
    assert parse_selector(selector) == expected


def test_empty_selector_is_rejected():
    with pytest.raises(SelectError, match="empty"):
        parse_selector("")


def test_prefix_without_expression_is_rejected():
    with pytest.raises(SelectError, match="missing an expression"):
        parse_selector("json:")


# --- JSONPath ---------------------------------------------------------


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("json:$.product.name", "Widget"),
        ("json:$.product.price.currency", "USD"),
        ("json:$.product.price.amount", "100.0"),
        ("json:$.stock.inStock", "true"),
        ("json:$.stock.count", "5"),
        # bare expression defaults to JSONPath
        ("$.product.name", "Widget"),
    ],
)
def test_jsonpath_extracts_scalars(selector, expected):
    assert extract(DOC, selector) == expected


def test_jsonpath_list_result_is_json_encoded():
    """A list that grows or shrinks must register as a change, so keep its structure."""
    assert extract(DOC, "json:$.reviews[*].rating") == "[5, 3]"


# --- jq ---------------------------------------------------------------


def test_jq_reports_a_missing_extra_clearly():
    """A plain install must say what to install, not raise ImportError."""
    if available_languages()["jq"]:
        pytest.skip("jq is installed here; the absence path cannot be exercised")
    with pytest.raises(SelectError, match=r"webscout-mcp\[json\]"):
        extract(DOC, "jq:.product.name")


def test_jq_extraction_when_installed():
    pytest.importorskip("jq", reason="jq is the optional half of the [json] extra")
    assert extract(DOC, "jq:.product.name") == "Widget"
    assert extract(DOC, "jq:.stock.count") == "5"
    assert extract(DOC, "jq:.reviews[].rating") == "[5, 3]"


def test_jq_missing_path_is_not_a_null_value():
    """jq yields None for a missing path; that must not look like a real null."""
    pytest.importorskip("jq")
    with pytest.raises(SelectError, match="matched nothing"):
        extract(DOC, "jq:.does.not.exist")


# --- failure behaviour ------------------------------------------------


def test_non_json_body_is_named_as_such():
    with pytest.raises(SelectError, match="not valid JSON"):
        extract("<html>not json</html>", "json:$.a")


def test_no_match_is_an_explicit_error():
    with pytest.raises(SelectError, match="matched nothing"):
        extract(DOC, "json:$.does.not.exist")


def test_malformed_jsonpath_becomes_a_wildcard_and_is_rejected():
    """Measured: `jsonpath` degrades bad syntax into a wildcard instead of raising.

    `$[[[` returns the whole document followed by every node inside it - 10 matches on a
    small document. For a monitor that means silently watching the whole response rather
    than one field, and recording a huge unstable string as the value. The signature is
    the document appearing first in a multi-match result, which no legitimate selector
    produces: `$..*` returns its nodes without the document first, and ordinary paths
    return one or two values.
    """
    with pytest.raises(SelectError, match="whole document"):
        extract(DOC, "json:$[[[")


def test_a_legitimate_recursive_wildcard_is_allowed():
    """The guard must not block selectors that genuinely match many nodes."""
    result = extract(DOC, "json:$..*")
    assert result.startswith(("[", "{")), result


def test_a_simple_miss_is_still_reported_as_no_match():
    """A path that simply does not exist stays a plain miss, not a wildcard warning."""
    with pytest.raises(SelectError, match="matched nothing"):
        extract(DOC, "json:$.a[")


def test_invalid_jq_expression_names_the_problem():
    """jq does raise on bad syntax, so that path gets a distinct message."""
    pytest.importorskip("jq")
    with pytest.raises(SelectError, match="invalid jq"):
        extract(DOC, "jq:.[[[")


# --- language availability -------------------------------------------


def test_available_languages_reports_both():
    langs = available_languages()
    assert set(langs) == {"jsonpath", "jq"}
    assert isinstance(langs["jsonpath"], bool)


# --- the value that gets watched -------------------------------------


def test_watching_one_field_ignores_changes_elsewhere():
    """The point of json_path: markup and neighbours churn, the watched field does not."""
    before = json.dumps({"price": 100.0, "name": "Widget", "stock": 5})
    after = json.dumps({"price": 100.0, "name": "Widget v2", "stock": 99})
    assert extract(before, "json:$.price") == extract(after, "json:$.price")


def test_watching_one_field_detects_its_own_change():
    before = json.dumps({"price": 100.0, "name": "Widget"})
    after = json.dumps({"price": 900.0, "name": "Widget"})
    assert extract(before, "json:$.price") != extract(after, "json:$.price")


# --- wiring ----------------------------------------------------------


def test_web_monitor_accepts_json_path():
    import inspect

    from webscout_mcp.server import create_server

    src = inspect.getsource(create_server)
    idx = src.find("async def web_monitor")
    assert idx != -1
    body = src[idx:]
    assert "json_path" in body[:4000], "the parameter must be declared"
    assert "json_select" in body, "the selector module must be used"
    assert "bypass_cache=True" in body, "monitoring must not read a cached body, or a changed page never registers"


def test_tool_description_mentions_the_extra():
    import asyncio

    from webscout_mcp.server import create_server

    tools = asyncio.run(create_server().list_tools())
    tool = next(t for t in tools if t.name == "web_monitor")
    desc = tool.description or ""
    assert "json_path" in desc
    assert "[json]" in desc, "the caller must learn which extra enables it"
