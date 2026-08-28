"""Tests for Google HTML search backend."""

import pytest

from webscout_mcp.search import GoogleHTMLBackend, SearchResult


class TestGoogleHTMLBackend:
    """Test Google HTML search backend."""

    def test_backend_name(self):
        assert GoogleHTMLBackend.name == "google"

    def test_google_url(self):
        assert GoogleHTMLBackend.GOOGLE_URL == "https://www.google.com/search"

    def test_parse_results_basic(self):
        html = """
        <html>
        <body>
        <div class="g">
            <div class="yuRUbf">
                <a href="https://example.com/page1">
                    <h3>Example Page 1</h3>
                </a>
            </div>
            <div class="VwiC3b">This is the first example snippet.</div>
        </div>
        <div class="g">
            <div class="yuRUbf">
                <a href="https://example.com/page2">
                    <h3>Example Page 2</h3>
                </a>
            </div>
            <div class="VwiC3b">This is the second example snippet.</div>
        </div>
        </body>
        </html>
        """
        results = GoogleHTMLBackend._parse_results(html, max_results=10)
        assert len(results) == 2
        assert results[0].title == "Example Page 1"
        assert results[0].url == "https://example.com/page1"
        assert results[0].snippet == "This is the first example snippet."
        assert results[0].backend == "google"
        assert results[0].position == 1

    def test_parse_results_max_results(self):
        html = """
        <html><body>
        <div class="g"><div class="yuRUbf"><a href="https://example.com/1"><h3>Page 1</h3></a></div></div>
        <div class="g"><div class="yuRUbf"><a href="https://example.com/2"><h3>Page 2</h3></a></div></div>
        <div class="g"><div class="yuRUbf"><a href="https://example.com/3"><h3>Page 3</h3></a></div></div>
        </body></html>
        """
        results = GoogleHTMLBackend._parse_results(html, max_results=2)
        assert len(results) == 2

    def test_parse_results_skip_google_links(self):
        html = """
        <html><body>
        <div class="g"><div class="yuRUbf"><a href="https://www.google.com/search?q=test"><h3>Google Link</h3></a></div></div>
        <div class="g"><div class="yuRUbf"><a href="https://example.com/page"><h3>Real Page</h3></a></div></div>
        </body></html>
        """
        results = GoogleHTMLBackend._parse_results(html, max_results=10)
        assert len(results) == 1
        assert results[0].url == "https://example.com/page"

    def test_parse_results_empty_html(self):
        results = GoogleHTMLBackend._parse_results("", max_results=10)
        assert len(results) == 0

    def test_parse_results_invalid_html(self):
        results = GoogleHTMLBackend._parse_results("not valid html <><>", max_results=10)
        assert len(results) == 0

    def test_parse_results_alternative_selectors(self):
        # Test with tF2Cxc selector
        html = """
        <html><body>
        <div class="tF2Cxc">
            <a href="https://example.com/alt"><h3>Alt Selector</h3></a>
            <div class="VwiC3b">Alt snippet</div>
        </div>
        </body></html>
        """
        results = GoogleHTMLBackend._parse_results(html, max_results=10)
        assert len(results) == 1
        assert results[0].title == "Alt Selector"

    def test_parse_results_no_title_fallback(self):
        html = """
        <html><body>
        <div class="g">
            <div class="yuRUbf">
                <a href="https://example.com/notitle">Link Text Only</a>
            </div>
        </div>
        </body></html>
        """
        results = GoogleHTMLBackend._parse_results(html, max_results=10)
        assert len(results) == 1
        assert results[0].title == "Link Text Only"

    def test_clean_text(self):
        # Test that _clean_text is inherited and works
        assert GoogleHTMLBackend._clean_text("  Hello  World  ") == "Hello World"
        assert GoogleHTMLBackend._clean_text("") == ""
