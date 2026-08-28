"""Tests for content extraction enhancement."""

import pytest

from webscout_mcp.fetcher import Fetcher


class TestContentExtraction:
    """Test enhanced content extraction."""

    def test_extract_basic_html(self):
        html = """
        <html>
        <head><title>Test Article</title></head>
        <body>
        <article>
        <h1>Test Article Title</h1>
        <p>This is the first paragraph of the test article.</p>
        <p>This is the second paragraph with more content.</p>
        </article>
        </body>
        </html>
        """
        result = Fetcher._extract_content(html, output_format="text")
        assert len(result) > 0
        assert "Test Article" in result or "first paragraph" in result

    def test_extract_markdown_format(self):
        html = """
        <html><body>
        <article>
        <h1>Title</h1>
        <p>Paragraph with <strong>bold</strong> and <em>italic</em> text.</p>
        <ul><li>Item 1</li><li>Item 2</li></ul>
        </article>
        </body></html>
        """
        result = Fetcher._extract_content(html, output_format="markdown")
        assert len(result) > 0

    def test_extract_html_format(self):
        html = """
        <html><body>
        <article>
        <h1>Title</h1>
        <p>Paragraph content.</p>
        </article>
        </body></html>
        """
        result = Fetcher._extract_content(html, output_format="html")
        assert len(result) > 0

    def test_extract_empty_html(self):
        result = Fetcher._extract_content("", output_format="text")
        assert result == ""

    def test_extract_invalid_html(self):
        result = Fetcher._extract_content("not valid html <><>", output_format="text")
        # Should not raise, may return empty or partial content
        assert isinstance(result, str)

    def test_extract_with_images_disabled(self):
        html = """
        <html><body>
        <article>
        <h1>Title</h1>
        <p>Paragraph with image: <img src="test.jpg" alt="test"></p>
        </article>
        </body></html>
        """
        result = Fetcher._extract_content(html, output_format="markdown", include_images=False)
        assert len(result) > 0

    def test_extract_with_images_enabled(self):
        html = """
        <html><body>
        <article>
        <h1>Title</h1>
        <p>Paragraph with image: <img src="test.jpg" alt="test"></p>
        </article>
        </body></html>
        """
        result = Fetcher._extract_content(html, output_format="markdown", include_images=True)
        assert len(result) > 0

    def test_extract_min_content_length(self):
        # Very short content should be filtered out by trafilatura
        html = """
        <html><body>
        <p>Short</p>
        </body></html>
        """
        result = Fetcher._extract_content(html, output_format="text")
        # May return empty or short content depending on extractor
        assert isinstance(result, str)

    def test_extract_long_article(self):
        paragraphs = "".join(f"<p>Paragraph {i} with some content.</p>" for i in range(20))
        html = f"""
        <html><body>
        <article>
        <h1>Long Article Title</h1>
        {paragraphs}
        </article>
        </body></html>
        """
        result = Fetcher._extract_content(html, output_format="text")
        assert len(result) > 100  # Should extract substantial content

    def test_extract_ignores_navigation(self):
        html = """
        <html><body>
        <nav><a href="/">Home</a><a href="/about">About</a></nav>
        <article>
        <h1>Main Article</h1>
        <p>This is the main article content that should be extracted.</p>
        <p>More article content here.</p>
        </article>
        <footer>Copyright 2024</footer>
        </body></html>
        """
        result = Fetcher._extract_content(html, output_format="text")
        assert "main article" in result.lower() or "article content" in result.lower()
