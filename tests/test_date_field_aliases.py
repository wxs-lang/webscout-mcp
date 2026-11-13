"""Published and modified are separate facts and must resolve at the same precision.

## Measured on real pages

    realpython   date='2026-10-24T14:00:00+00:00' [json-ld]
                 published='2026-10-24'            [semantic-html]   <- same fact, different precision
                 modified -> missing                                 <- never read
    mozilla      published='2026-03-17T10:55:45.000Z' [semantic-html]
                 modified -> missing

The alias tables only knew one date concept:

    _JSON_LD_ALIASES  "date" -> (datePublished, dateCreated, uploadDate)
    _META_ALIASES     "date" -> (article:published_time, article:modified_time)

So `modified` mapped to nothing despite `dateModified` being declared, and `published` fell
through to semantic HTML even when the page stated it in JSON-LD.

## Why the precision matters

A caller comparing `date` and `published` on the same page saw `...T14:00:00+00:00` beside
`2026-10-24` and could not tell they agreed. Equal facts should not look like different ones.

## What stays the same

`date` still prefers `datePublished`. Modification time changes on every edit and would make
"date" useless for judging a page's age - that ordering is deliberate and pinned below.
"""

from __future__ import annotations

import pytest

from webscout_mcp.schema_extractor import SOURCE_JSON_LD, SOURCE_META, extract_by_schema

# Both dates declared, as an article usually does.
BOTH_DATES = """
<script type="application/ld+json">
{
  "@type": "Article",
  "headline": "A Title",
  "datePublished": "2024-03-01T09:00:00+00:00",
  "dateModified": "2025-07-15T18:30:00+00:00"
}
</script>
"""

META_BOTH = """
<meta property="article:published_time" content="2024-03-01T09:00:00+00:00">
<meta property="article:modified_time" content="2025-07-15T18:30:00+00:00">
"""


def _extract(html: str, *fields: str):
    schema = {"type": "object", "properties": {f: {"type": "string"} for f in fields}}
    return extract_by_schema(f"<html><head>{html}</head><body></body></html>", schema, "https://example.com/a")


def test_modified_resolves_from_json_ld():
    """Previously reached nothing at all."""
    result = _extract(BOTH_DATES, "modified")
    assert result.data["modified"] == "2025-07-15T18:30:00+00:00"
    assert result.sources["modified"] == SOURCE_JSON_LD


def test_published_and_date_agree_on_precision():
    """The defect: the same fact came back at two precisions."""
    result = _extract(BOTH_DATES, "date", "published")
    assert result.data["date"] == result.data["published"], (
        f"date={result.data['date']!r} published={result.data['published']!r}"
    )
    assert result.sources["date"] == result.sources["published"] == SOURCE_JSON_LD


def test_date_still_prefers_the_published_value():
    """Modification time must not win: it changes on every edit."""
    result = _extract(BOTH_DATES, "date")
    assert result.data["date"] == "2024-03-01T09:00:00+00:00"


def test_both_resolve_from_meta_when_that_is_all_there_is():
    result = _extract(META_BOTH, "published", "modified")
    assert result.data["published"] == "2024-03-01T09:00:00+00:00"
    assert result.data["modified"] == "2025-07-15T18:30:00+00:00"
    assert result.sources["published"] == SOURCE_META


def test_modified_is_reported_missing_when_only_published_exists():
    """Honest absence, not a copy of the published date."""
    html = '<script type="application/ld+json">{"datePublished": "2024-03-01T09:00:00Z"}</script>'
    result = _extract(html, "published", "modified")
    assert result.data["published"] == "2024-03-01T09:00:00Z"
    assert result.data.get("modified") in (None, "")
    assert "modified" in result.missing


def test_keywords_resolve_when_declared():
    html = '<script type="application/ld+json">{"keywords": "python, asyncio"}</script>'
    result = _extract(html, "keywords")
    assert result.data["keywords"] == "python, asyncio"


@pytest.mark.parametrize("field", ["published", "modified", "keywords"])
def test_new_fields_are_absent_not_wrong(field):
    """A page with no dates must not invent one."""
    result = _extract("<title>Nothing</title>", field)
    assert result.data.get(field) in (None, ""), field
