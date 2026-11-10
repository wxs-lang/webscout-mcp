"""Schema-driven extraction: describe the data, get an object back.

Derivation, not an LLM: no API key, no per-call cost, deterministic. The cost of that choice
is that an unseen structure yields null rather than a guess - which is why provenance is
recorded per field and `missing` is explicit.

The resolution order is the design: JSON-LD (the page states it), then meta tags, then
semantics. Tests pin the order, not just the values, because a value pulled from an `<h1>`
and one taken from JSON-LD look identical in `data` and are not equally trustworthy.
"""

from __future__ import annotations

import pytest

from webscout_mcp.schema_extractor import (
    SOURCE_JSON_LD,
    SOURCE_META,
    SOURCE_NONE,
    SOURCE_SEMANTIC,
    extract_by_schema,
)

PRODUCT_HTML = """<!DOCTYPE html>
<html><head>
<title>Fallback Title</title>
<meta property="og:description" content="A great widget for testing.">
<script type="application/ld+json">
{"@type":"Product","name":"Widget Pro","price":"49.99","priceCurrency":"USD",
 "brand":{"name":"Acme"},"datePublished":"2026-01-15"}
</script>
</head><body><h1>Semantic Heading</h1><span class="price">$99.99</span></body></html>"""

SEMANTIC_ONLY_HTML = """<!DOCTYPE html>
<html><head><title>Bare page</title></head>
<body><h1>Heading Title</h1>
<time datetime="2026-03-01">March 1</time>
<div class="author">Jane Doe</div>
</body></html>"""

EMPTY_HTML = "<html><head></head><body></body></html>"


def test_json_ld_wins_over_everything():
    """The page stated it, so nothing should be inferred instead."""
    r = extract_by_schema(PRODUCT_HTML, {"properties": {"name": {"type": "string"}}}, "https://example.com/")
    assert r.data["name"] == "Widget Pro"
    assert r.sources["name"] == SOURCE_JSON_LD
    # The <h1> said something different; JSON-LD must win.
    assert r.data["name"] != "Semantic Heading"


def test_nested_json_ld_values_are_lifted():
    """`brand: {name: ...}` is the common shape; the inner value is what callers want."""
    r = extract_by_schema(PRODUCT_HTML, {"properties": {"brand": {"type": "string"}}}, "https://example.com/")
    assert r.data["brand"] == "Acme"
    assert r.sources["brand"] == SOURCE_JSON_LD


def test_declared_number_type_is_coerced():
    """A schema that asks for a number should not receive the string '49.99'."""
    r = extract_by_schema(PRODUCT_HTML, {"properties": {"price": {"type": "number"}}}, "https://example.com/")
    assert r.data["price"] == 49.99
    assert isinstance(r.data["price"], float)


def test_currency_symbols_are_stripped_for_numbers():
    """A class hint named `price` supplies a schema field also named `price`."""
    html = PRODUCT_HTML.replace('"price":"49.99"', '"nope":"x"').replace('"priceCurrency":"USD"', "")
    r = extract_by_schema(html, {"properties": {"price": {"type": "number"}}}, "https://example.com/")
    assert r.data["price"] == 99.99, "the $ must be stripped before float conversion"


def test_a_field_name_the_page_does_not_use_stays_null():
    """The honest limit of derivation: `expensive` is not a class on the page.

    A caller that invents a field name unconnected to the markup gets null with no source.
    Silently returning the nearest price would be worse - it looks correct and is not.
    """
    r = extract_by_schema(PRODUCT_HTML, {"properties": {"expensive": {"type": "number"}}}, "https://example.com/")
    assert r.data["expensive"] is None
    assert r.sources["expensive"] == SOURCE_NONE
    assert r.missing == ["expensive"]


def test_meta_is_used_when_json_ld_has_nothing():
    r = extract_by_schema(PRODUCT_HTML, {"properties": {"description": {"type": "string"}}}, "https://example.com/")
    assert r.data["description"] == "A great widget for testing."
    assert r.sources["description"] == SOURCE_META


def test_document_title_beats_the_heading():
    """`<title>` is what the page declares; an `<h1>` is a rendering of it.

    Measured: a page with `<title>Bare page</title>` and `<h1>Heading Title</h1>` resolves
    `title` to 'Bare page' from the meta layer. That is right - the heading is a display
    choice, the title is the document's own name.
    """
    r = extract_by_schema(SEMANTIC_ONLY_HTML, {"properties": {"title": {"type": "string"}}}, "https://example.com/")
    assert r.data["title"] == "Bare page"
    assert r.sources["title"] == SOURCE_META


def test_semantics_are_the_last_resort():
    """When no title tag exists, the heading is the only source left."""
    no_title = SEMANTIC_ONLY_HTML.replace("<title>Bare page</title>", "")
    r = extract_by_schema(no_title, {"properties": {"title": {"type": "string"}}}, "https://example.com/")
    assert r.data["title"] == "Heading Title"
    assert r.sources["title"] == SOURCE_SEMANTIC


def test_time_element_supplies_a_date():
    r = extract_by_schema(SEMANTIC_ONLY_HTML, {"properties": {"date": {"type": "string"}}}, "https://example.com/")
    assert r.data["date"] == "2026-03-01"
    assert r.sources["date"] == SOURCE_SEMANTIC


def test_an_unresolvable_field_is_null_and_listed():
    """A null with no source is information; a guessed value would not be."""
    r = extract_by_schema(EMPTY_HTML, {"properties": {"price": {"type": "number"}}}, "https://example.com/")
    assert r.data["price"] is None
    assert r.sources["price"] == SOURCE_NONE
    assert r.missing == ["price"]
    assert r.resolved == 0


def test_resolved_counts_what_was_found():
    r = extract_by_schema(
        PRODUCT_HTML,
        {
            "properties": {
                "name": {"type": "string"},
                "price": {"type": "number"},
                "absent_field": {"type": "string"},
            }
        },
        "https://example.com/",
    )
    assert r.resolved == 2
    assert r.missing == ["absent_field"]


def test_report_shape_is_stable():
    """Callers index into this; the keys should not drift."""
    payload = extract_by_schema(
        PRODUCT_HTML, {"properties": {"name": {"type": "string"}}}, "https://example.com/"
    ).to_dict()
    assert set(payload) == {"url", "data", "sources", "missing", "resolved", "requested"}


def test_empty_html_does_not_raise():
    r = extract_by_schema("", {"properties": {"name": {"type": "string"}}}, "")
    assert r.data == {}


def test_malformed_schema_shape_is_tolerated():
    """Only `properties` is used; anything else is ignored, not rejected."""
    r = extract_by_schema(PRODUCT_HTML, {"type": "object"}, "https://example.com/")
    assert r.data == {}
    r2 = extract_by_schema(PRODUCT_HTML, {"properties": "not-a-dict"}, "https://example.com/")
    assert r2.data == {}


def test_broken_html_still_yields_metadata():
    """Parsers are lenient; a missing close tag should not lose the head."""
    broken = PRODUCT_HTML.replace("</html>", "")
    r = extract_by_schema(broken, {"properties": {"name": {"type": "string"}}}, "https://example.com/")
    assert r.data["name"] == "Widget Pro"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("yes", True), ("false", False), ("0", False)],
)
def test_declared_boolean_type_is_coerced(raw, expected):
    html = f'<html><head><meta property="og:description" content="{raw}"></head><body></body></html>'
    r = extract_by_schema(html, {"properties": {"description": {"type": "boolean"}}}, "https://example.com/")
    assert r.data["description"] is expected
