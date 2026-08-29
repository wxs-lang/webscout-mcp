"""
Tests for enhanced features:
- Multi-backend search merging
- Relevance-based result ranking
- URL normalization
- Text cleaning
- Crawler retry and delay
- Crawler smart link filtering
- Error classification
"""

from webscout_mcp import Config
from webscout_mcp.crawler import Crawler, CrawlResult
from webscout_mcp.fetcher import Fetcher
from webscout_mcp.search import (
    SearchBackend,
    SearchEngine,
    SearchResult,
)


class TestSearchEnhancements:
    """Tests for search enhancements."""

    def test_relevance_calculation(self):
        """Test relevance score calculation."""
        result = SearchResult(
            title="Python Async Programming Tutorial",
            url="https://example.com/python-async",
            snippet="Learn how to use asyncio for asynchronous programming in Python",
            position=1,
            backend="test",
        )
        score = SearchEngine._calculate_relevance(result, "python async programming")
        assert score > 0, "Relevance score should be positive for matching content"

    def test_relevance_no_match(self):
        """Test relevance score with no matching terms."""
        result = SearchResult(
            title="Completely unrelated content",
            url="https://example.com/unrelated",
            snippet="Nothing to do with the search query here",
            position=1,
            backend="test",
        )
        score = SearchEngine._calculate_relevance(result, "python async programming")
        assert score == 0, "Relevance score should be zero for non-matching content"

    def test_relevance_short_snippet_penalty(self):
        """Test that short snippets get a penalty."""
        result_long = SearchResult(
            title="Python Tutorial",
            url="https://example.com/python",
            snippet="A" * 50,  # Long snippet
            position=1,
            backend="test",
        )
        result_short = SearchResult(
            title="Python Tutorial",
            url="https://example.com/python",
            snippet="Short",  # Short snippet (< 20 chars)
            position=1,
            backend="test",
        )
        score_long = SearchEngine._calculate_relevance(result_long, "python")
        score_short = SearchEngine._calculate_relevance(result_short, "python")
        assert score_long > score_short, "Long snippet should score higher than short snippet"

    def test_rank_results(self):
        """Test result ranking by relevance."""
        engine = SearchEngine(Config())
        results = [
            SearchResult(title="Unrelated", url="https://a.com", snippet="x", position=1, backend="test"),
            SearchResult(title="Python Async", url="https://b.com", snippet="python async", position=2, backend="test"),
            SearchResult(title="Python", url="https://c.com", snippet="python", position=3, backend="test"),
        ]
        ranked = engine._rank_results(results, "python async")
        assert ranked[0].title == "Python Async", "Most relevant result should be first"
        assert ranked[0].position == 1, "Positions should be renumbered"

    def test_deduplicate_results(self):
        """Test result deduplication."""
        results = [
            SearchResult(title="A", url="https://example.com/page", snippet="x", position=1, backend="test"),
            SearchResult(title="B", url="https://example.com/page/", snippet="y", position=2, backend="test"),
            SearchResult(title="C", url="https://example.com/other", snippet="z", position=3, backend="test"),
        ]
        unique = SearchEngine._deduplicate_results(results)
        assert len(unique) == 2, "Should have 2 unique results (duplicate removed)"
        assert unique[0].position == 1, "Positions should be renumbered"
        assert unique[1].position == 2, "Positions should be renumbered"

    def test_url_normalization(self):
        """Test URL normalization."""
        # Remove tracking params
        url1 = "https://example.com/page?utm_source=twitter&utm_medium=social&id=123"
        normalized1 = SearchBackend._normalize_url(url1)
        assert "utm_source" not in normalized1, "Tracking params should be removed"
        assert "id=123" in normalized1, "Non-tracking params should be kept"

        # Lowercase host
        url2 = "HTTPS://Example.COM/Page"
        normalized2 = SearchBackend._normalize_url(url2)
        assert "example.com" in normalized2, "Host should be lowercased"

        # Remove trailing slash
        url3 = "https://example.com/page/"
        normalized3 = SearchBackend._normalize_url(url3)
        assert not normalized3.endswith("/"), "Trailing slash should be removed"

    def test_text_cleaning(self):
        """Test text cleaning."""
        # Multiple spaces
        assert SearchBackend._clean_text("hello   world") == "hello world"
        # Newlines and tabs
        assert SearchBackend._clean_text("hello\n\tworld") == "hello world"
        # Leading/trailing whitespace
        assert SearchBackend._clean_text("  hello world  ") == "hello world"
        # Empty string
        assert SearchBackend._clean_text("") == ""
        assert SearchBackend._clean_text(None) == ""

    def test_error_classification(self):
        """Test error classification."""
        # Transient errors
        assert Crawler._classify_error("Connection timeout") == "transient"
        assert Crawler._classify_error("500 Internal Server Error") == "transient"
        assert Crawler._classify_error("Connection refused") == "transient"
        assert Crawler._classify_error("Too Many Requests") == "transient"

        # Permanent errors
        assert Crawler._classify_error("404 Not Found") == "permanent"
        assert Crawler._classify_error("403 Forbidden") == "permanent"
        assert Crawler._classify_error("Invalid URL") == "permanent"


class TestCrawlerEnhancements:
    """Tests for crawler enhancements."""

    def test_crawl_result_statistics(self):
        """Test CrawlResult statistics fields."""
        result = CrawlResult(seed_url="https://example.com")
        result.retries = 5
        result.avg_response_time = 1.23

        data = result.to_dict()
        assert data["retries"] == 5
        assert data["avg_response_time"] == 1.23

    def test_link_filtering(self):
        """Test smart link filtering."""
        crawler = Crawler(Config(), Fetcher(Config()))
        visited = set()
        seed_domain = "example.com"

        links = [
            "https://example.com/page1",
            "https://example.com/page1",  # Duplicate
            "https://example.com/page2",
            "https://other.com/page",  # Different domain
            "https://example.com/file.pdf",  # Non-content
            "https://example.com/login",  # Login page
            "https://example.com/admin",  # Admin page
        ]

        filtered = crawler._filter_links(links, visited, True, seed_domain)
        assert len(filtered) == 2, "Should only keep valid same-domain content pages"
        assert "https://example.com/page1" in filtered
        assert "https://example.com/page2" in filtered

    def test_link_filtering_allows_different_domain_when_disabled(self):
        """Test that different domains are allowed when same_domain_only is False."""
        crawler = Crawler(Config(), Fetcher(Config()))
        visited = set()
        seed_domain = "example.com"

        links = [
            "https://example.com/page1",
            "https://other.com/page2",
        ]

        filtered = crawler._filter_links(links, visited, False, seed_domain)
        assert len(filtered) == 2, "Should keep both domains when same_domain_only is False"


class TestConfigEnhancements:
    """Tests for new configuration options."""

    def test_search_merge_backends_default(self):
        """Test default value for search_merge_backends."""
        config = Config()
        assert config.search_merge_backends is False

    def test_crawler_delay_default(self):
        """Test default value for crawler_delay."""
        config = Config()
        assert config.crawler_delay == 0.0

    def test_crawler_max_retries_default(self):
        """Test default value for crawler_max_retries."""
        config = Config()
        assert config.crawler_max_retries == 2

    def test_search_merge_backends_from_env(self, monkeypatch):
        """Test search_merge_backends from environment variable."""
        monkeypatch.setenv("WEBSCOUT_SEARCH_MERGE_BACKENDS", "true")
        config = Config.from_env()
        assert config.search_merge_backends is True

    def test_crawler_delay_from_env(self, monkeypatch):
        """Test crawler_delay from environment variable."""
        monkeypatch.setenv("WEBSCOUT_CRAWLER_DELAY", "2.5")
        config = Config.from_env()
        assert config.crawler_delay == 2.5

    def test_crawler_max_retries_from_env(self, monkeypatch):
        """Test crawler_max_retries from environment variable."""
        monkeypatch.setenv("WEBSCOUT_CRAWLER_MAX_RETRIES", "5")
        config = Config.from_env()
        assert config.crawler_max_retries == 5


class TestSearchResultDataclass:
    """Tests for SearchResult dataclass enhancements."""

    def test_relevance_score_field(self):
        """Test that SearchResult has relevance_score field."""
        result = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="test",
            position=1,
        )
        assert hasattr(result, "relevance_score")
        assert result.relevance_score == 0.0

    def test_search_result_to_dict(self):
        """Test SearchResult serialization."""
        result = SearchResult(
            title="Test",
            url="https://example.com",
            snippet="test",
            position=1,
            backend="bing",
            relevance_score=4.5,
        )
        # Should be serializable to JSON
        import json

        data = result.__dict__
        json_str = json.dumps(data)
        assert "relevance_score" in json_str
        assert "4.5" in json_str
