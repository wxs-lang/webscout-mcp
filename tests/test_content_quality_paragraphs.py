"""content_quality must count paragraphs on text that still has paragraph breaks.

## Measured on a real article (4015 words, rust-book)

    output_format="text"       double_newline=0    paragraph_count=1
    output_format="markdown"   double_newline=79   paragraph_count=80

The plain-text extractor collapses blank lines, and `analyze()` splits paragraphs on `\\n\\n`.
So `paragraph_count` was a constant 1 for every page fetched through the tool.

`word_count` was identical in both formats - which is why this survived: the number a reader
checks first was right, and the structural metric beside it was not.

## Why the metric matters

`ContentQualityMetrics.paragraph_count` feeds the scoring path (`> 3` thresholds). A constant
1 does not merely misreport, it removes structure from the score on every page.

## The wrong fix, recorded

Splitting on single newlines instead would count soft wraps: the text format wraps at ~98
columns. Measured, that would give 278 "paragraphs" for this page - a different wrong number.
"""

from __future__ import annotations

import pytest

from webscout_mcp.extras.content_quality import analyze_content_quality

# Two paragraphs separated by a blank line, each with a soft wrap inside it.
TWO_PARAGRAPHS = (
    "First paragraph starts here and continues\n"
    "after a soft wrap that is not a paragraph break.\n"
    "\n"
    "Second paragraph begins after the blank line and\n"
    "also soft wraps before it ends."
)


def test_blank_lines_separate_paragraphs():
    metrics = analyze_content_quality(TWO_PARAGRAPHS, html="")
    assert metrics.paragraph_count == 2


def test_soft_wraps_are_not_paragraph_breaks():
    """Single newlines inside a paragraph must not inflate the count."""
    metrics = analyze_content_quality(TWO_PARAGRAPHS, html="")
    assert metrics.paragraph_count == 2, "a soft wrap was counted as a paragraph"


def test_collapsed_text_loses_the_count():
    """Documents the failure mode the tool was hitting.

    When blank lines are gone, the analyzer can only see one block - this is what the
    `text` output format produced, and why the tool had to switch to `markdown`.
    """
    collapsed = TWO_PARAGRAPHS.replace("\n\n", "\n")
    metrics = analyze_content_quality(collapsed, html="")
    assert metrics.paragraph_count == 1


def test_word_count_is_unaffected_by_format():
    """The metric that looked fine, for contrast."""
    with_breaks = analyze_content_quality(TWO_PARAGRAPHS, html="")
    collapsed = analyze_content_quality(TWO_PARAGRAPHS.replace("\n\n", "\n"), html="")
    assert with_breaks.word_count == collapsed.word_count


@pytest.mark.parametrize("count", [1, 2, 5, 10])
def test_paragraph_count_tracks_the_real_structure(count):
    text = "\n\n".join(f"Paragraph number {i} with a few words in it." for i in range(count))
    metrics = analyze_content_quality(text, html="")
    assert metrics.paragraph_count == count


def test_the_tool_requests_a_format_that_keeps_breaks():
    """Source-level: the call site must not ask for the collapsing format again."""
    import inspect

    from webscout_mcp.server import create_server

    source = inspect.getsource(create_server)
    start = source.find("async def content_quality")
    assert start != -1
    end = source.find("@mcp.tool", start + 1)
    body = source[start : end if end != -1 else len(source)]

    assert 'output_format="markdown"' in body, (
        "content_quality does not request a format that preserves paragraph breaks"
    )
    offending = [
        line.strip() for line in body.splitlines() if 'output_format="text"' in line and "extract=True" in line
    ]
    assert not offending, f"content_quality still requests the collapsing format: {offending}"
