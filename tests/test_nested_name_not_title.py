"""A nested `name` must not become the page title.

## The defect, measured on a live article

`web_extract_schema` on realpython.com returned:

    title        = 'Leodanis Pozo Ramos'      [json-ld]
    author       = 'Leodanis Pozo Ramos'      [json-ld]

The same string for both, and it is the author - the article's actual title
("Python's asyncio: A Hands-On Walkthrough") was missing. `metadata_extract` had the right
title, so the flattening was at fault, not the source.

## The cause

`_flatten_json_ld` lifted `author: {name: X}` to `flat["author"] = X` correctly, then recursed
into the same object, where `{name: X}` wrote `flat["name"] = X` at the **top level**. `title`'s
alias list contains `name`, so the title resolved to the author.

## Why the existing tests missed it

They used fixtures where the title lived at the root and nothing nested carried a `name`.
The bug only appears when both exist - which is the common shape for article JSON-LD.

These fixtures reproduce that shape.
"""

from __future__ import annotations

import pytest

from webscout_mcp.schema_extractor import extract_by_schema

ARTICLE_LD = """
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "The Actual Headline",
  "author": {"@type": "Person", "name": "The Author Name"},
  "publisher": {"@type": "Organization", "name": "The Publisher Name"}
}
</script>
"""

HTML_WITH_BOTH = f"<html><head>{ARTICLE_LD}<title>Doc Title</title></head><body></body></html>"

SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}}}


def test_title_is_not_the_author_name():
    """The live defect: author.name leaked into the root `name`."""
    result = extract_by_schema(HTML_WITH_BOTH, SCHEMA, base_url="https://example.com/a")
    assert result.data["title"] != "The Author Name", "the nested author name was used as the document title"


def test_title_resolves_to_the_headline():
    result = extract_by_schema(HTML_WITH_BOTH, SCHEMA, base_url="https://example.com/a")
    assert result.data["title"] == "The Actual Headline"


def test_the_author_still_resolves_from_its_own_key():
    """The lift that put it on `author` must keep working."""
    schema = {"type": "object", "properties": {"author": {"type": "string"}}}
    result = extract_by_schema(HTML_WITH_BOTH, schema, base_url="https://example.com/a")
    assert result.data["author"] == "The Author Name"


def test_an_organization_name_does_not_become_the_title():
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "WebSite", "publisher": {"@type": "Organization", "name": "Pub Co"}}'
        "</script><title>Site Title</title></head><body></body></html>"
    )
    result = extract_by_schema(html, schema, base_url="https://example.com/")
    assert result.data["title"] != "Pub Co"


def test_a_root_level_name_still_counts_as_title():
    """A document that legitimately declares `name` at the root must keep resolving."""
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "WebPage", "name": "Root Declared Name"}'
        "</script></head><body></body></html>"
    )
    result = extract_by_schema(html, SCHEMA, base_url="https://example.com/")
    assert result.data["title"] == "Root Declared Name"


@pytest.mark.parametrize(
    "nested_key",
    ["author", "publisher", "creator", "reviewedBy"],
)
def test_any_nested_person_or_org_name_stays_off_the_root(nested_key):
    html = (
        '<html><head><script type="application/ld+json">'
        '{"@type": "Article", "headline": "Real Title", '
        f'"{nested_key}": {{"@type": "Person", "name": "Someone Else"}}'
        "}</script></head><body></body></html>"
    )
    result = extract_by_schema(html, SCHEMA, base_url="https://example.com/a")
    assert result.data["title"] == "Real Title", nested_key
