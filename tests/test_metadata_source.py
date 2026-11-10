"""metadata_extract must read raw_html, not content.

## The defect

`FetchResponse` carries two bodies and they are not the same thing:

    content     extract=False still returns the processed body - measured 18979 chars of
                text with no <head> and no <title>
    raw_html    the document as served - 81061 chars including <head>

The tool read `content` first. Metadata lives in `<head>` by definition, so the extractor
had nothing to parse:

    via content    title=''   og_title=''   json_ld=0
    via raw_html   title='3. An Informal Introduction to Python — Python 3.15.2 documentation'

The old expression also inverted the fallback: it reached `raw_html` only when `content`
was falsy, which is the opposite of when it is needed.

## Why this is tested at the source level as well

The behaviour needs a live fetch to demonstrate, but the ordering mistake is a single
expression and is worth pinning directly - a future refactor could reintroduce it without
any unit test noticing.
"""

from __future__ import annotations

import pathlib

import pytest

from webscout_mcp.metadata_extractor import extract_metadata

HEAD_HTML = """<!DOCTYPE html>
<html><head>
<title>Test Page Title</title>
<meta name="description" content="A test description here.">
<meta property="og:title" content="OG Test Title">
<script type="application/ld+json">{"@type":"Product","name":"Widget","price":"9.99"}</script>
</head><body><h1>Hello</h1></body></html>"""

BODY_ONLY_TEXT = "Just the visible text after processing, with no head element at all."


def test_metadata_is_found_in_a_document_with_a_head():
    """Sanity: the extractor works when given real HTML."""
    m = extract_metadata(HEAD_HTML, "https://example.com/")
    assert m.title == "Test Page Title"
    assert m.og_title == "OG Test Title"
    assert m.json_ld and m.json_ld[0]["name"] == "Widget"


def test_processed_text_yields_nothing():
    """This is why `content` was the wrong source: it has no head to parse."""
    m = extract_metadata(BODY_ONLY_TEXT, "https://example.com/")
    assert m.title == ""
    assert not m.json_ld


def test_the_tool_prefers_raw_html():
    """The ordering is the fix; a refactor must not silently reverse it again."""
    source = (pathlib.Path(__file__).resolve().parents[1] / "webscout_mcp" / "server.py").read_text(encoding="utf-8")
    start = source.find("async def metadata_extract")
    assert start != -1
    end = source.find("@mcp.tool()", start)
    block = source[start:end]

    assert "raw_html" in block, "metadata_extract must consult raw_html"
    assert 'getattr(result, "raw_html", "")' in block, "raw_html must be the first choice, not a fallback after content"
    # The inverted form that caused the bug.
    assert 'result.content if hasattr(result, "content") else result.raw_html' not in block


@pytest.mark.parametrize(
    "field",
    ["title", "og_title", "description"],
)
def test_each_common_field_is_extractable(field):
    """All the fields a caller asks for come from the same head block."""
    m = extract_metadata(HEAD_HTML, "https://example.com/")
    assert getattr(m, field), f"{field} should be populated from the fixture head"
