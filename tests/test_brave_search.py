"""Tests for Brave HTML search backend."""
import pytest
from webscout_mcp.search import BraveHTMLBackend, SearchResult


class TestBraveHTMLBackend:
    """Test Brave HTML search backend."""

    def test_backend_name(self):
        assert BraveHTMLBackend.name == "brave"

    def test_brave_url(self):
        assert BraveHTMLBackend.BRAVE_URL == "https://search.brave.com/search"

    def test_parse_results_basic(self):
        html = """
        <html>
        <body>
        <div class="snippet">
            <a class="result-header" href="https://example.com/page1">
                <h2>Example Page 1</h2>
            </a>
            <div class="snippet-content">This is the first example snippet.</div>
        </div>
        <div class="snippet">
            <a class="result-header" href="https://example.com/page2">
                <h2>Example Page 2</h2>
            </a>
            <div class="snippet-content">This is the second example snippet.</div>
        </div>
        </body>
        </html>
        """
        results = BraveHTMLBackend._parse_results(html, max_results=10)
        assert len(results) == 2
        assert results[0].title == "Example Page 1"
        assert results[0].url == "https://example.com/page1"
        assert results[0].snippet == "This is the first example snippet."
        assert results[0].backend == "brave"
        assert results[0].position == 1

    def test_parse_results_max_results(self):
        html = """
        <html><body>
        <div class="snippet"><a class="result-header" href="https://example.com/1"><h2>Page 1</h2></a></div>
        <div class="snippet"><a class="result-header" href="https://example.com/2"><h2>Page 2</h2></a></div>
        <div class="snippet"><a class="result-header" href="https://example.com/3"><h2>Page 3</h2></a></div>
        </body></html>
        """
        results = BraveHTMLBackend._parse_results(html, max_results=2)
        assert len(results) == 2

    def test_parse_results_skip_brave_links(self):
        html = """
        <html><body>
        <div class="snippet"><a class="result-header" href="https://brave.com/search?q=test"><h2>Brave Link</h2></a></div>
        <div class="snippet"><a class="result-header" href="https://example.com/page"><h2>Real Page</h2></a></div>
        </body></html>
        """
        results = BraveHTMLBackend._parse_results(html, max_results=10)
        assert len(results) == 1
        assert results[0].url == "https://example.com/page"

    def test_parse_results_empty_html(self):
        results = BraveHTMLBackend._parse_results("", max_results=10)
        assert len(results) == 0

    def test_parse_results_invalid_html(self):
        results = BraveHTMLBackend._parse_results("not valid html <><>", max_results=10)
        assert len(results) == 0

    def test_parse_results_alternative_selectors(self):
        # Test with div.result selector
        html = """
        <html><body>
        <div class="result">
            <a class="title" href="https://example.com/alt"><h2>Alt Selector</h2></a>
            <p class="snippet">Alt snippet</p>
        </div>
        </body></html>
        """
        results = BraveHTMLBackend._parse_results(html, max_results=10)
        assert len(results) == 1
        assert results[0].title == "Alt Selector"

    def test_parse_results_no_title_fallback(self):
        html = """
        <html><body>
        <div class="snippet">
            <a class="result-header" href="https://example.com/notitle">Link Text Only</a>
        </div>
        </body></html>
        """
        results = BraveHTMLBackend._parse_results(html, max_results=10)
        assert len(results) == 1
        assert results[0].title == "Link Text Only"

    def test_clean_text(self):
        # Test that _clean_text is inherited and works
        assert BraveHTMLBackend._clean_text("  Hello  World  ") == "Hello World"
        assert BraveHTMLBackend._clean_text("") == ""
