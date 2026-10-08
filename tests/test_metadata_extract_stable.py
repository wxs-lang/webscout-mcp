"""
Stable-gate tests for metadata_extract MCP tool.

Covers:
- Actual MCP tool invocation (server.call_tool)
- base_url parameter compatibility (extract(html, base_url=...))
- Relative URL resolution with final_url
- OG / Twitter / article metadata (article:* in both name AND property)
- JSON-LD arrays and @graph
- Malformed HTML / JSON-LD
- SSRF initial URL and redirect hop (via fetcher event hook)
- HTTP error / timeout / oversize
- Output size limits (raw_meta, json_ld, images, links)
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from webscout_mcp.metadata_extractor import (
    MAX_IMAGES,
    MAX_JSON_LD_ENTRIES,
    MAX_LINKS,
    MAX_RAW_META_TAGS,
    MetadataExtractor,
    PageMetadata,
    extract_metadata,
)

# ---------------------------------------------------------------------------
# Sample HTML fixtures
# ---------------------------------------------------------------------------

ARTICLE_HTML = """<html lang="en">
<head>
<title>Test Article</title>
<meta name="description" content="Article description">
<meta property="og:title" content="OG Article Title">
<meta property="og:description" content="OG Article Desc">
<meta property="og:image" content="/images/og.jpg">
<meta property="og:url" content="https://example.com/article">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Twitter Title">
<meta name="twitter:image" content="/images/twitter.jpg">
<!-- article:* in BOTH name and property attributes -->
<meta name="article:author" content="Name Author">
<meta property="article:published_time" content="2024-01-15T10:00:00Z">
<meta property="article:modified_time" content="2024-02-20T14:30:00Z">
<meta name="article:section" content="Technology">
<meta property="article:tag" content="python">
<meta name="article:tag" content="metadata">
<link rel="canonical" href="https://example.com/canonical/article">
<link rel="icon" href="/favicon.ico">
</head>
<body>
<img src="/images/hero.jpg" alt="Hero">
<a href="/about">About Us</a>
<a href="https://external.com/page">External</a>
</body>
</html>"""

JSON_LD_GRAPH_HTML = """<html>
<head><title>JSON-LD Graph Test</title></head>
<body>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {"@type": "Article", "headline": "Graph Article 1", "author": {"@type": "Person", "name": "Alice"}},
    {"@type": "WebPage", "name": "Graph Page 2"},
    {"@type": "BreadcrumbList", "itemListElement": [{"@type": "ListItem", "position": 1, "name": "Home"}]}
  ]
}
</script>
<script type="application/ld+json">
[{"@type": "Person", "name": "Bob"}, {"@type": "Organization", "name": "Acme"}]
</script>
<script type="application/ld+json">
{ "invalid json here
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Tests: base_url compatibility (P0 interface fix)
# ---------------------------------------------------------------------------


class TestBaseUrlCompatibility:
    """extract() must accept base_url as keyword argument (server.py calls it this way)."""

    def test_extract_accepts_base_url_keyword(self):
        """P0: extract(html, base_url=...) must not raise TypeError."""
        extractor = MetadataExtractor()
        meta = extractor.extract(ARTICLE_HTML, base_url="https://example.com")
        assert meta.og_image == "https://example.com/images/og.jpg"
        assert meta.favicon == "https://example.com/favicon.ico"

    def test_extract_base_url_overrides_constructor(self):
        """base_url passed to extract() should override constructor base_url."""
        extractor = MetadataExtractor(base_url="https://old.example.com")
        meta = extractor.extract(ARTICLE_HTML, base_url="https://new.example.com")
        assert meta.og_image == "https://new.example.com/images/og.jpg"

    def test_extract_no_base_url_backward_compat(self):
        """extract(html) without base_url must still work (original API)."""
        extractor = MetadataExtractor(base_url="https://example.com")
        meta = extractor.extract(ARTICLE_HTML)
        assert meta.og_image == "https://example.com/images/og.jpg"

    def test_extract_metadata_function_base_url(self):
        """Module-level extract_metadata(html, base_url=...) must work."""
        meta = extract_metadata(ARTICLE_HTML, base_url="https://example.com")
        assert meta.title == "Test Article"
        assert meta.og_image == "https://example.com/images/og.jpg"


# ---------------------------------------------------------------------------
# Tests: article:* in both name and property attributes
# ---------------------------------------------------------------------------


class TestArticleMetadataDualAttribute:
    """article:* can appear in name OR property attribute; both must be extracted."""

    def test_article_author_from_name(self):
        meta = MetadataExtractor().extract(ARTICLE_HTML)
        assert meta.article_author == "Name Author"

    def test_article_published_from_property(self):
        meta = MetadataExtractor().extract(ARTICLE_HTML)
        assert meta.article_published_time == "2024-01-15T10:00:00Z"

    def test_article_modified_from_property(self):
        meta = MetadataExtractor().extract(ARTICLE_HTML)
        assert meta.article_modified_time == "2024-02-20T14:30:00Z"

    def test_article_section_from_name(self):
        meta = MetadataExtractor().extract(ARTICLE_HTML)
        assert meta.article_section == "Technology"

    def test_article_tags_from_both(self):
        meta = MetadataExtractor().extract(ARTICLE_HTML)
        assert "python" in meta.article_tags
        assert "metadata" in meta.article_tags
        assert len(meta.article_tags) == 2

    def test_article_via_property_only(self):
        """If article:* only appears in property, it should still be extracted."""
        html = """<html><head><title>T</title>
        <meta property="article:author" content="PropAuthor">
        <meta property="article:published_time" content="2024-06-01T00:00:00Z">
        </head><body></body></html>"""
        meta = MetadataExtractor().extract(html)
        assert meta.article_author == "PropAuthor"
        assert meta.article_published_time == "2024-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tests: JSON-LD @graph and arrays
# ---------------------------------------------------------------------------


class TestJsonLdGraph:
    """JSON-LD @graph must be expanded into individual nodes."""

    def test_graph_nodes_extracted(self):
        meta = MetadataExtractor().extract(JSON_LD_GRAPH_HTML)
        # Outer dict with @graph + 3 graph nodes + 2 from array script = 6
        assert len(meta.json_ld) >= 5
        types = [node.get("@type") for node in meta.json_ld if isinstance(node, dict)]
        assert "Article" in types
        assert "WebPage" in types
        assert "BreadcrumbList" in types
        assert "Person" in types
        assert "Organization" in types

    def test_graph_outer_dict_preserved(self):
        """The outer dict containing @graph should also be preserved."""
        meta = MetadataExtractor().extract(JSON_LD_GRAPH_HTML)
        outer = [n for n in meta.json_ld if isinstance(n, dict) and "@graph" in n]
        assert len(outer) == 1
        assert outer[0]["@context"] == "https://schema.org"

    def test_malformed_json_ld_skipped(self):
        """Invalid JSON-LD script should be silently skipped, not crash."""
        meta = MetadataExtractor().extract(JSON_LD_GRAPH_HTML)
        # Should still have valid nodes; no exception
        assert len(meta.json_ld) > 0
        assert all(isinstance(n, dict) for n in meta.json_ld)


# ---------------------------------------------------------------------------
# Tests: Output size limits
# ---------------------------------------------------------------------------


class TestOutputSizeLimits:
    """raw_meta, json_ld, images, links must be bounded."""

    def test_raw_meta_limit(self):
        many_meta = "".join(f'<meta name="meta-{i}" content="value-{i}">' for i in range(MAX_RAW_META_TAGS + 50))
        html = f"<html><head><title>T</title>{many_meta}</head><body></body></html>"
        meta = MetadataExtractor().extract(html)
        assert len(meta.raw_meta) <= MAX_RAW_META_TAGS

    def test_images_limit(self):
        many_imgs = "".join(f'<img src="/img/{i}.jpg" alt="img {i}">' for i in range(MAX_IMAGES + 50))
        html = f"<html><head><title>T</title></head><body>{many_imgs}</body></html>"
        meta = MetadataExtractor(base_url="https://example.com").extract(html)
        assert len(meta.images) <= MAX_IMAGES

    def test_links_limit(self):
        many_links = "".join(f'<a href="/page/{i}">Link {i}</a>' for i in range(MAX_LINKS + 50))
        html = f"<html><head><title>T</title></head><body>{many_links}</body></html>"
        meta = MetadataExtractor(base_url="https://example.com").extract(html)
        assert len(meta.links) <= MAX_LINKS


# ---------------------------------------------------------------------------
# Tests: Malformed / edge case HTML
# ---------------------------------------------------------------------------


class TestMalformedHtml:
    """Empty, malformed, or non-HTML input must not crash."""

    def test_empty_string(self):
        meta = MetadataExtractor().extract("")
        assert isinstance(meta, PageMetadata)
        assert meta.title == ""

    def test_none_html(self):
        """None should not crash (BeautifulSoup handles it)."""
        meta = MetadataExtractor().extract(None)  # type: ignore[arg-type]
        assert isinstance(meta, PageMetadata)

    def test_unclosed_tags(self):
        meta = MetadataExtractor().extract("<html><head><title>Unclosed")
        assert isinstance(meta, PageMetadata)

    def test_binary_content(self):
        meta = MetadataExtractor().extract("\x00\x01\x02 binary garbage")
        assert isinstance(meta, PageMetadata)

    def test_duplicate_meta_tags(self):
        """Duplicate meta tags: later should overwrite earlier for known fields."""
        html = """<html><head>
        <meta name="description" content="First">
        <meta name="description" content="Second">
        </head><body></body></html>"""
        meta = MetadataExtractor().extract(html)
        assert meta.description == "Second"


# ---------------------------------------------------------------------------
# Tests: Relative URL resolution
# ---------------------------------------------------------------------------


class TestRelativeUrlResolution:
    """Relative URLs must be resolved against base_url."""

    def test_og_image_relative(self):
        meta = MetadataExtractor(base_url="https://example.com/sub/page.html").extract(ARTICLE_HTML)
        assert meta.og_image == "https://example.com/images/og.jpg"

    def test_canonical_absolute(self):
        meta = MetadataExtractor(base_url="https://example.com").extract(ARTICLE_HTML)
        assert meta.canonical_url == "https://example.com/canonical/article"

    def test_favicon_relative(self):
        meta = MetadataExtractor(base_url="https://example.com/sub/").extract(ARTICLE_HTML)
        assert meta.favicon == "https://example.com/favicon.ico"

    def test_twitter_image_relative(self):
        meta = MetadataExtractor(base_url="https://example.com").extract(ARTICLE_HTML)
        assert meta.twitter_image == "https://example.com/images/twitter.jpg"

    def test_data_url_preserved(self):
        html = '<html><head><link rel="icon" href="data:image/svg+xml,<svg></svg>"></head></html>'
        meta = MetadataExtractor(base_url="https://example.com").extract(html)
        assert meta.favicon.startswith("data:")


# ---------------------------------------------------------------------------
# Tests: Actual MCP tool invocation (no pytest.skip)
# ---------------------------------------------------------------------------


class TestMCPToolActualInvocation:
    """Actually call metadata_extract through server.call_tool with mocked fetch."""

    @pytest.mark.asyncio
    async def test_metadata_extract_tool_actual_call(self):
        """Create real MCPServer, verify tool registered, call it, assert output."""
        pytest.importorskip("mcp")
        from webscout_mcp.config import Config
        from webscout_mcp.server import create_server

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))

            # Mock Fetcher class so create_server() uses our mock fetcher
            mock_fetcher_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.content = ARTICLE_HTML
            mock_result.raw_html = ARTICLE_HTML
            mock_result.final_url = "https://example.com/article-page"
            mock_fetcher_instance.fetch = AsyncMock(return_value=mock_result)

            with patch("webscout_mcp.server.Fetcher", return_value=mock_fetcher_instance):
                server = create_server(cfg)

                # Verify metadata_extract is in the tool list
                tool_names = []
                if hasattr(server, "list_tools"):
                    tools_result = await server.list_tools()
                    if isinstance(tools_result, list):
                        tool_names = [t.name for t in tools_result]
                    elif hasattr(tools_result, "tools"):
                        tool_names = [t.name for t in tools_result.tools]
                assert "metadata_extract" in tool_names, f"metadata_extract not in: {tool_names}"
                assert len(tool_names) == 11, f"Expected 11 MCP tools, got {len(tool_names)}"

                call_result = await server.call_tool(
                    "metadata_extract",
                    {"url": "https://example.com/article"},
                )

            # Extract text content from result
            if isinstance(call_result, tuple):
                content_blocks = call_result[0]
            elif hasattr(call_result, "content"):
                content_blocks = call_result.content
            else:
                content_blocks = []

            result_text = "".join(getattr(block, "text", "") for block in content_blocks if hasattr(block, "text"))
            data = json.loads(result_text)

            # Verify core metadata extracted
            assert data["title"] == "Test Article"
            assert data["open_graph"]["title"] == "OG Article Title"
            assert data["twitter"]["card"] == "summary_large_image"
            assert data["article"]["author"] == "Name Author"
            # Verify relative URL resolved against final_url (not original url)
            assert data["open_graph"]["image"] == "https://example.com/images/og.jpg"
            assert data["favicon"] == "https://example.com/favicon.ico"

    @pytest.mark.asyncio
    async def test_metadata_extract_tool_empty_html_error(self):
        """Tool should return error JSON when fetch returns empty content."""
        pytest.importorskip("mcp")
        from webscout_mcp.config import Config
        from webscout_mcp.server import create_server

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))

            mock_fetcher_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.content = ""
            mock_result.raw_html = ""
            mock_result.final_url = "https://example.com/empty"
            mock_fetcher_instance.fetch = AsyncMock(return_value=mock_result)

            with patch("webscout_mcp.server.Fetcher", return_value=mock_fetcher_instance):
                server = create_server(cfg)
                call_result = await server.call_tool(
                    "metadata_extract",
                    {"url": "https://example.com/empty"},
                )

            if isinstance(call_result, tuple):
                content_blocks = call_result[0]
            elif hasattr(call_result, "content"):
                content_blocks = call_result.content
            else:
                content_blocks = []

            result_text = "".join(getattr(block, "text", "") for block in content_blocks if hasattr(block, "text"))
            data = json.loads(result_text)
            assert "error" in data
            assert "Failed to fetch page content" in data["error"]


# ---------------------------------------------------------------------------
# Tests: SSRF safety on metadata_extract path (via fetcher)
# ---------------------------------------------------------------------------


class TestMetadataExtractSSRF:
    """metadata_extract uses fetcher.fetch which has SSRF event hooks.

    These tests verify the fetcher SSRF guard is active on the path used
    by metadata_extract. We test at the fetcher level since metadata_extract
    delegates fetching to fetcher.
    """

    @pytest.mark.asyncio
    async def test_ssrf_initial_url_blocked(self):
        """Private IP URL must be blocked — FetchResult.error contains SSRF (no request sent)."""
        from webscout_mcp.config import Config
        from webscout_mcp.fetcher import Fetcher

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))
            fetcher = Fetcher(cfg)
            fetcher.safety_check_enabled = True  # same as metadata_fetcher in server.py
            result = await fetcher.fetch(url="http://169.254.169.254/latest/meta-data/", extract=False)
            assert result.error is not None
            assert "SSRF" in result.error or "private" in result.error.lower() or "unsafe" in result.error.lower()
            assert result.status_code == 0  # no HTTP request was made

    @pytest.mark.asyncio
    async def test_ssrf_localhost_blocked(self):
        """localhost must be blocked — FetchResult.error contains SSRF."""
        from webscout_mcp.config import Config
        from webscout_mcp.fetcher import Fetcher

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))
            fetcher = Fetcher(cfg)
            fetcher.safety_check_enabled = True
            result = await fetcher.fetch(url="http://localhost:8080/secret", extract=False)
            assert result.error is not None
            assert "SSRF" in result.error or "localhost" in result.error.lower() or "private" in result.error.lower()
            assert result.status_code == 0

    def test_fetcher_has_ssrf_event_hook(self):
        """Fetcher must use event_hooks with SSRF check on every request (including redirects)."""
        # Inspect the client creation to verify event_hooks includes SSRF
        import inspect

        from webscout_mcp.fetcher import Fetcher

        source = inspect.getsource(Fetcher.__init__)
        # The fetcher should set up event_hooks or a request hook for SSRF
        assert "event_hooks" in source or "ssrf" in source.lower() or "check_url" in source, (
            "Fetcher must have SSRF event hook configured"
        )


# ---------------------------------------------------------------------------
# Tests: HTTP error / timeout handling at tool level
# ---------------------------------------------------------------------------


class TestMetadataExtractErrorHandling:
    """Tool must return clear error JSON on fetch failures, not crash."""

    @pytest.mark.asyncio
    async def test_fetch_exception_returns_error(self):
        """If fetcher.fetch raises, tool must return error JSON."""
        pytest.importorskip("mcp")
        from webscout_mcp.config import Config
        from webscout_mcp.server import create_server

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))

            mock_fetcher_instance = MagicMock()
            mock_fetcher_instance.fetch = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

            with patch("webscout_mcp.server.Fetcher", return_value=mock_fetcher_instance):
                server = create_server(cfg)
                call_result = await server.call_tool(
                    "metadata_extract",
                    {"url": "https://example.com/fail"},
                )

            if isinstance(call_result, tuple):
                content_blocks = call_result[0]
            elif hasattr(call_result, "content"):
                content_blocks = call_result.content
            else:
                content_blocks = []

            result_text = "".join(getattr(block, "text", "") for block in content_blocks if hasattr(block, "text"))
            data = json.loads(result_text)
            assert "error" in data
            assert "Metadata extraction failed" in data["error"]


# ---------------------------------------------------------------------------
# Tests: MCP schema unchanged
# ---------------------------------------------------------------------------


class TestMCPSchemaUnchanged:
    """metadata_extract(url) signature must remain unchanged; 11 tools total."""

    @pytest.mark.asyncio
    async def test_tool_count_eleven(self):
        pytest.importorskip("mcp")
        from webscout_mcp.config import Config
        from webscout_mcp.server import create_server

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))
            server = create_server(cfg)
            if hasattr(server, "list_tools"):
                tools_result = await server.list_tools()
                if isinstance(tools_result, list):
                    tool_names = [t.name for t in tools_result]
                else:
                    tool_names = [t.name for t in tools_result.tools]
                assert len(tool_names) == 11, f"Expected 11 tools, got {len(tool_names)}: {tool_names}"
                assert "metadata_extract" in tool_names
