"""
Tests for metadata_extractor module.
"""

from webscout_mcp.metadata_extractor import (
    MetadataExtractor,
    PageMetadata,
    extract_metadata,
)


class TestPageMetadata:
    """Tests for PageMetadata dataclass."""

    def test_default_values(self):
        """Test default values."""
        meta = PageMetadata()
        assert meta.title == ""
        assert meta.description == ""
        assert meta.keywords == []
        assert meta.author == ""
        assert meta.language == ""
        assert meta.canonical_url == ""
        assert meta.favicon == ""
        assert meta.robots == ""
        assert meta.og_title == ""
        assert meta.og_description == ""
        assert meta.og_image == ""
        assert meta.og_url == ""
        assert meta.og_type == ""
        assert meta.twitter_card == ""
        assert meta.twitter_title == ""
        assert meta.twitter_description == ""
        assert meta.twitter_image == ""
        assert meta.raw_meta == {}

    def test_to_dict(self):
        """Test to_dict method."""
        meta = PageMetadata(
            title="Test Title",
            description="Test Description",
            keywords=["python", "test"],
            author="Test Author",
            language="en",
            og_title="OG Title",
            og_description="OG Description",
            og_image="https://example.com/image.jpg",
            twitter_card="summary_large_image",
        )
        data = meta.to_dict()
        assert data["title"] == "Test Title"
        assert data["description"] == "Test Description"
        assert data["keywords"] == ["python", "test"]
        assert data["author"] == "Test Author"
        assert data["language"] == "en"
        assert data["open_graph"]["title"] == "OG Title"
        assert data["open_graph"]["description"] == "OG Description"
        assert data["open_graph"]["image"] == "https://example.com/image.jpg"
        assert data["twitter"]["card"] == "summary_large_image"

    def test_get_best_title(self):
        """Test get_best_title method."""
        # HTML title only
        meta1 = PageMetadata(title="HTML Title")
        assert meta1.get_best_title() == "HTML Title"

        # OG title preferred
        meta2 = PageMetadata(title="HTML Title", og_title="OG Title")
        assert meta2.get_best_title() == "OG Title"

        # Twitter title preferred over HTML but not OG
        meta3 = PageMetadata(title="HTML Title", twitter_title="Twitter Title")
        assert meta3.get_best_title() == "Twitter Title"

        # OG > Twitter > HTML
        meta4 = PageMetadata(
            title="HTML Title",
            og_title="OG Title",
            twitter_title="Twitter Title",
        )
        assert meta4.get_best_title() == "OG Title"

    def test_get_best_description(self):
        """Test get_best_description method."""
        meta = PageMetadata(
            description="Meta Description",
            og_description="OG Description",
            twitter_description="Twitter Description",
        )
        assert meta.get_best_description() == "OG Description"

    def test_get_best_image(self):
        """Test get_best_image method."""
        meta = PageMetadata(
            og_image="https://example.com/og.jpg",
            twitter_image="https://example.com/twitter.jpg",
        )
        assert meta.get_best_image() == "https://example.com/og.jpg"


class TestMetadataExtractor:
    """Tests for MetadataExtractor class."""

    def test_extract_basic_metadata(self):
        """Test extraction of basic metadata."""
        html = """
        <html lang="en">
        <head>
            <title>Test Page Title</title>
            <meta name="description" content="This is a test page description">
            <meta name="keywords" content="python, test, metadata">
            <meta name="author" content="Test Author">
            <meta charset="UTF-8">
        </head>
        <body><h1>Hello</h1></body>
        </html>
        """
        extractor = MetadataExtractor()
        meta = extractor.extract(html)
        assert meta.title == "Test Page Title"
        assert meta.description == "This is a test page description"
        assert meta.keywords == ["python", "test", "metadata"]
        assert meta.author == "Test Author"
        assert meta.language == "en"
        assert meta.charset == "UTF-8"

    def test_extract_open_graph(self):
        """Test extraction of Open Graph metadata."""
        html = """
        <html>
        <head>
            <title>Test</title>
            <meta property="og:title" content="OG Title">
            <meta property="og:description" content="OG Description">
            <meta property="og:image" content="https://example.com/image.jpg">
            <meta property="og:url" content="https://example.com/page">
            <meta property="og:type" content="article">
            <meta property="og:site_name" content="Example Site">
        </head>
        <body></body>
        </html>
        """
        extractor = MetadataExtractor(base_url="https://example.com")
        meta = extractor.extract(html)
        assert meta.og_title == "OG Title"
        assert meta.og_description == "OG Description"
        assert meta.og_image == "https://example.com/image.jpg"
        assert meta.og_url == "https://example.com/page"
        assert meta.og_type == "article"
        assert meta.og_site_name == "Example Site"

    def test_extract_twitter(self):
        """Test extraction of Twitter metadata."""
        html = """
        <html>
        <head>
            <title>Test</title>
            <meta name="twitter:card" content="summary_large_image">
            <meta name="twitter:title" content="Twitter Title">
            <meta name="twitter:description" content="Twitter Description">
            <meta name="twitter:image" content="/images/twitter.jpg">
            <meta name="twitter:creator" content="@testuser">
        </head>
        <body></body>
        </html>
        """
        extractor = MetadataExtractor(base_url="https://example.com")
        meta = extractor.extract(html)
        assert meta.twitter_card == "summary_large_image"
        assert meta.twitter_title == "Twitter Title"
        assert meta.twitter_description == "Twitter Description"
        assert meta.twitter_image == "https://example.com/images/twitter.jpg"
        assert meta.twitter_creator == "@testuser"

    def test_extract_canonical_and_favicon(self):
        """Test extraction of canonical URL and favicon."""
        html = """
        <html>
        <head>
            <title>Test</title>
            <link rel="canonical" href="https://example.com/canonical">
            <link rel="icon" href="/favicon.ico">
        </head>
        <body></body>
        </html>
        """
        extractor = MetadataExtractor(base_url="https://example.com")
        meta = extractor.extract(html)
        assert meta.canonical_url == "https://example.com/canonical"
        assert meta.favicon == "https://example.com/favicon.ico"

    def test_extract_robots_and_technical(self):
        """Test extraction of robots and technical metadata."""
        html = """
        <html>
        <head>
            <title>Test</title>
            <meta name="robots" content="index, follow">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <meta name="generator" content="WordPress 6.0">
            <meta name="theme-color" content="#ffffff">
        </head>
        <body></body>
        </html>
        """
        extractor = MetadataExtractor()
        meta = extractor.extract(html)
        assert meta.robots == "index, follow"
        assert meta.viewport == "width=device-width, initial-scale=1.0"
        assert meta.generator == "WordPress 6.0"
        assert meta.theme_color == "#ffffff"

    def test_extract_raw_meta(self):
        """Test that raw meta tags are stored."""
        html = """
        <html>
        <head>
            <title>Test</title>
            <meta name="custom-meta" content="custom-value">
            <meta property="custom:property" content="property-value">
        </head>
        <body></body>
        </html>
        """
        extractor = MetadataExtractor()
        meta = extractor.extract(html)
        assert meta.raw_meta.get("custom-meta") == "custom-value"
        assert meta.raw_meta.get("custom:property") == "property-value"

    def test_relative_url_resolution(self):
        """Test that relative URLs are resolved to absolute URLs."""
        html = """
        <html>
        <head>
            <title>Test</title>
            <meta property="og:image" content="/images/og.jpg">
            <link rel="icon" href="../favicon.ico">
        </head>
        <body></body>
        </html>
        """
        extractor = MetadataExtractor(base_url="https://example.com/sub/page.html")
        meta = extractor.extract(html)
        assert meta.og_image == "https://example.com/images/og.jpg"
        assert meta.favicon == "https://example.com/favicon.ico"

    def test_empty_html(self):
        """Test extraction from empty HTML."""
        extractor = MetadataExtractor()
        meta = extractor.extract("")
        assert meta.title == ""
        assert meta.description == ""
        assert meta.keywords == []

    def test_invalid_html(self):
        """Test extraction from invalid HTML (should not crash)."""
        extractor = MetadataExtractor()
        meta = extractor.extract("<html><head><title>Unclosed")
        # Should not crash, may extract partial data
        assert isinstance(meta, PageMetadata)


class TestExtractMetadataFunction:
    """Tests for extract_metadata convenience function."""

    def test_extract_metadata_function(self):
        """Test the convenience function."""
        html = """
        <html>
        <head>
            <title>Test Title</title>
            <meta name="description" content="Test Description">
        </head>
        <body></body>
        </html>
        """
        meta = extract_metadata(html, base_url="https://example.com")
        assert meta.title == "Test Title"
        assert meta.description == "Test Description"
        assert isinstance(meta, PageMetadata)
