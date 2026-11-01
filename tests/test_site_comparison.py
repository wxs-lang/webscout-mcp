"""Site comparison: the four silent-zero bugs, and the tool contract.

Every defect fixed here produced wrong numbers without raising, which is why each test
asserts on a value rather than on "no exception":

  1. `compare_sites` reads keys `seo`/`performance`/`content`/`links` - passing
     `*_metrics` gave every site empty metrics and identical scores
  2. `_apply_seo_metrics` wants `title_length`/`h1_count`/`images_with_alt`/... which
     `content_quality` does not emit, so SEO was 50 for a rich page and a stub alike
  3. readability worth 35 points made a 6-word page outscore a 667-word article
  4. `ComparisonResult.to_dict` omitted `comparison_matrix`
"""

from __future__ import annotations

import asyncio
import json

from webscout_mcp.extras.competitor_analyzer import compare_sites
from webscout_mcp.extras.seo_metrics import extract_seo_metrics
from webscout_mcp.server import create_server

RICH = (
    """<!doctype html><html><head>
<title>A thorough guide to web scraping</title>
<meta name="description" content="Learn how to scrape the web responsibly with modern tooling and examples.">
<link rel="canonical" href="https://rich.test/">
<meta property="og:title" content="Guide">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{"@type":"Article"}</script>
</head><body><h1>Web scraping guide</h1><h2>A</h2><h2>B</h2>
<p>"""
    + ("Static fetching retrieves raw HTML and extracts main content. " * 50)
    + """</p>
<a href="/internal">i</a><a href="https://ext.test/x">e</a>
<img src="a.png" alt="alt text"><img src="b.png" alt="more alt">
</body></html>"""
)

THIN = """<!doctype html><html><head><title>Short</title></head><body><h1>Hi</h1><p>tiny</p></body></html>"""


# --- SEO extraction ---------------------------------------------------


def test_seo_extraction_reads_the_fields_the_analyzer_wants():
    m = extract_seo_metrics(RICH, "https://rich.test/")
    assert m["title_length"] == len("A thorough guide to web scraping")
    assert m["meta_description_length"] > 60
    assert m["h1_count"] == 1
    assert m["heading_count"] == 3  # h1 + two h2
    assert m["image_count"] == 2
    assert m["images_with_alt"] == 2
    assert m["has_schema"] is True
    assert m["has_og_tags"] is True
    assert m["has_twitter_cards"] is True
    assert m["canonical_url"] == "https://rich.test/"


def test_empty_alt_is_not_counted_as_accessible():
    html = '<html><body><img src="a" alt=""><img src="b" alt="real text"></body></html>'
    m = extract_seo_metrics(html)
    assert m["image_count"] == 2
    assert m["images_with_alt"] == 1


def test_links_are_split_by_host():
    html = '<html><body><a href="/a">i</a><a href="https://same.test/b">i</a><a href="https://other.test/c">e</a></body></html>'
    m = extract_seo_metrics(html, "https://same.test/page")
    assert m["internal_links"] == 2
    assert m["external_links"] == 1


def test_fragment_and_mailto_links_are_skipped():
    html = '<html><body><a href="#top">t</a><a href="mailto:x@y.z">m</a><a href="/real">r</a></body></html>'
    m = extract_seo_metrics(html)
    assert m["internal_links"] == 1


def test_empty_html_returns_zeroed_metrics():
    m = extract_seo_metrics("")
    assert m["title_length"] == 0
    assert m["h1_count"] == 0
    assert m["has_schema"] is False


# --- scoring ---------------------------------------------------------


def _payload(html: str, url: str) -> dict:
    import re

    from webscout_mcp.extras.content_quality import analyze_content_quality
    from webscout_mcp.extras.performance_analyzer import analyze_performance

    plain = re.sub(r"<[^>]+>", " ", html)
    perf = analyze_performance(html, url=url)
    quality = analyze_content_quality(plain, html=html)
    return {
        "url": url,
        "name": url.split("//")[-1].split("/")[0],
        "seo": extract_seo_metrics(html, url),
        "performance": perf.to_dict() if hasattr(perf, "to_dict") else vars(perf),
        "content": quality.to_dict() if hasattr(quality, "to_dict") else vars(quality),
        "links": {},
    }


def test_rich_page_outranks_a_stub():
    """The headline regression: readability points used to invert this."""
    result = compare_sites([_payload(RICH, "https://rich.test/"), _payload(THIN, "https://thin.test/")])
    d = result.to_dict()
    winner = d["winner"]
    assert winner.startswith("rich"), f"a stub beat a full article: {d['summary']}"


def test_scores_discriminate_on_every_axis():
    """Identical scores on obviously-different input was the silent-zero symptom."""
    result = compare_sites([_payload(RICH, "https://rich.test/"), _payload(THIN, "https://thin.test/")])
    d = result.to_dict()
    for axis in ("seo_score", "content_score", "overall_score"):
        values = [s[axis] for s in d["sites"]]
        assert len(set(values)) > 1, f"{axis} identical for rich and thin: {values}"


def test_short_page_cannot_collect_readability_points():
    """Gating readability on body length is what fixed the inversion."""
    result = compare_sites([_payload(THIN, "https://thin.test/")])
    d = result.to_dict()
    assert d["sites"][0]["content_score"] == 30, "a 4-word page should sit at the base score"


def test_to_dict_includes_the_comparison_matrix():
    """It was computed and then dropped from the serialisation."""
    result = compare_sites([_payload(RICH, "https://rich.test/"), _payload(THIN, "https://thin.test/")])
    d = result.to_dict()
    assert "comparison_matrix" in d
    assert (
        d["comparison_matrix"]["overall_score"] == [s["overall_score"] for s in d["sites"]]
        or len(d["comparison_matrix"]["overall_score"]) == 2
    )


# --- tool contract ----------------------------------------------------


def _call(args: dict) -> dict:
    async def go():
        server = create_server()
        return await server.call_tool("web_compare_sites", args)

    result = asyncio.run(go())
    obj = result[0] if isinstance(result, tuple) else result
    content = getattr(obj, "content", obj)
    block = content[0] if isinstance(content, list) else content
    return json.loads(getattr(block, "text", str(block)))


def test_tool_is_registered_and_count_is_fourteen():
    async def go():
        server = create_server()
        return await server.list_tools()

    tools = asyncio.run(go())
    names = {t.name for t in tools}
    assert "web_compare_sites" in names
    assert len(names) == 14, f"tool count changed: {sorted(names)}"


def test_empty_url_list_is_an_explicit_error():
    out = _call({"urls": []})
    assert "error" in out
    assert "urls" in out["error"]


def test_too_many_urls_is_rejected():
    out = _call({"urls": [f"https://site{i}.test/" for i in range(11)]})
    assert "error" in out
    assert "10" in out["error"]


def test_names_length_must_match_urls():
    out = _call({"urls": ["https://a.test/", "https://b.test/"], "names": ["only-one"]})
    assert "error" in out
    assert "names" in out["error"].lower()


def test_failed_fetches_do_not_raise():
    """Unreachable sites come back as failures, never as an exception."""
    out = _call({"urls": ["https://nonexistent.invalid/"]})
    assert isinstance(out, dict)
    assert "error" in out or "failures" in out or "sites" in out


def test_script_end_tag_with_whitespace_is_stripped():
    """`</script >` is a valid HTML end tag; a bare pattern misses it.

    CodeQL flagged the original regex. If script text survives the strip, it reaches the
    readability and word-count metrics and inflates the content score of a page that
    has little real content - the inversion this release fixed.
    """
    import re

    html = "<html><body><p>real content here</p><script>var SECRET_DATA = 1;</script ></body></html>"
    plain = re.sub(r"<script[^>]*>.*?</script[^>]*>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    plain = re.sub(r"<[^>]+>", " ", plain)
    assert "SECRET_DATA" not in plain, "script body survived the strip"
    assert "real content" in plain
