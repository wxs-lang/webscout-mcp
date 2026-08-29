"""Tests for search optimizer module."""

import time

from webscout_mcp.search_optimizer import (
    QueryUnderstanding,
    SearchCache,
    SearchOptimizer,
    SearchRanker,
    SearchResponse,
    SearchResultItem,
    optimized_search,
)


class TestSearchResultItem:
    """Test SearchResultItem class."""

    def test_creation(self):
        item = SearchResultItem(title="Test", url="https://example.com")
        assert item.title == "Test"
        assert item.url == "https://example.com"
        assert item.final_score == 0.0

    def test_to_dict(self):
        item = SearchResultItem(
            title="Test",
            url="https://example.com",
            snippet="Test snippet",
            final_score=0.85,
            confidence=0.9,
        )
        data = item.to_dict()
        assert data["title"] == "Test"
        assert data["final_score"] == 0.85
        assert data["confidence"] == 0.9


class TestSearchResponse:
    """Test SearchResponse class."""

    def test_creation(self):
        resp = SearchResponse(query="test")
        assert resp.query == "test"
        assert resp.total_results == 0

    def test_to_dict(self):
        resp = SearchResponse(
            query="test",
            total_results=5,
            backends_queried=["bing", "duckduckgo"],
            response_time_ms=150.5,
        )
        data = resp.to_dict()
        assert data["query"] == "test"
        assert data["total_results"] == 5
        assert data["backends_queried"] == ["bing", "duckduckgo"]


class TestQueryUnderstanding:
    """Test QueryUnderstanding class."""

    def test_creation(self):
        qu = QueryUnderstanding()
        assert qu is not None

    def test_detect_intent_navigational(self):
        qu = QueryUnderstanding()
        assert qu.detect_intent("go to github.com") == "navigational"
        assert qu.detect_intent("open facebook.com") == "navigational"

    def test_detect_intent_informational(self):
        qu = QueryUnderstanding()
        assert qu.detect_intent("what is python") == "informational"
        assert qu.detect_intent("how to learn programming") == "informational"
        assert qu.detect_intent("explain machine learning") == "informational"

    def test_detect_intent_transactional(self):
        qu = QueryUnderstanding()
        assert qu.detect_intent("buy laptop") == "transactional"
        assert qu.detect_intent("best python tutorial") == "transactional"

    def test_expand_query(self):
        qu = QueryUnderstanding()
        expanded = qu.expand_query("learn js")
        assert "javascript" in expanded

    def test_rewrite_query(self):
        qu = QueryUnderstanding()
        rewritten, changed = qu.rewrite_query("learn js")
        assert "javascript" in rewritten
        assert changed is True

    def test_rewrite_query_no_change(self):
        qu = QueryUnderstanding()
        rewritten, changed = qu.rewrite_query("learn python programming")
        assert changed is False

    def test_extract_keywords(self):
        qu = QueryUnderstanding()
        keywords = qu.extract_keywords("what is the best python tutorial")
        assert "python" in keywords
        assert "tutorial" in keywords
        assert "what" not in keywords  # Stop word removed

    def test_extract_keywords_all_stopwords(self):
        qu = QueryUnderstanding()
        keywords = qu.extract_keywords("the a an")
        assert len(keywords) > 0  # Falls back to all words


class TestSearchCache:
    """Test SearchCache class."""

    def test_creation(self):
        cache = SearchCache(ttl=60, max_size=100)
        assert cache.ttl == 60
        assert cache.size == 0

    def test_set_and_get(self):
        cache = SearchCache(ttl=60)
        response = SearchResponse(query="test", total_results=5)
        cache.set("test", 10, ["bing"], response)
        assert cache.size == 1

        cached = cache.get("test", 10, ["bing"])
        assert cached is not None
        assert cached.cache_hit is True
        assert cached.total_results == 5

    def test_get_miss(self):
        cache = SearchCache()
        assert cache.get("nonexistent", 10, ["bing"]) is None

    def test_cache_expiration(self):
        cache = SearchCache(ttl=0)  # Immediate expiration
        response = SearchResponse(query="test")
        cache.set("test", 10, ["bing"], response)
        time.sleep(0.1)
        assert cache.get("test", 10, ["bing"]) is None

    def test_cache_max_size(self):
        cache = SearchCache(max_size=2)
        for i in range(5):
            cache.set(f"query{i}", 10, ["bing"], SearchResponse(query=f"query{i}"))
        assert cache.size <= 2

    def test_clear(self):
        cache = SearchCache()
        cache.set("test", 10, ["bing"], SearchResponse())
        assert cache.size == 1
        cache.clear()
        assert cache.size == 0


class TestSearchRanker:
    """Test SearchRanker class."""

    def test_creation(self):
        ranker = SearchRanker()
        assert ranker is not None

    def test_calculate_relevance(self):
        ranker = SearchRanker()
        result = SearchResultItem(
            title="Python Programming Tutorial",
            url="https://example.com/python",
            snippet="Learn Python programming from scratch",
        )
        score = ranker.calculate_relevance(result, "python tutorial")
        assert 0 <= score <= 1
        assert score > 0.5  # Should be relevant

    def test_calculate_relevance_low(self):
        ranker = SearchRanker()
        result = SearchResultItem(
            title="Cooking Recipes",
            url="https://example.com/food",
            snippet="Delicious recipes for every occasion",
        )
        score = ranker.calculate_relevance(result, "python programming")
        assert score < 0.3  # Should not be relevant

    def test_calculate_authority_high(self):
        ranker = SearchRanker()
        result = SearchResultItem(url="https://github.com/user/repo")
        score = ranker.calculate_authority(result)
        assert score >= 0.9

    def test_calculate_authority_low(self):
        ranker = SearchRanker()
        result = SearchResultItem(url="http://unknown-site-12345.com/page")
        score = ranker.calculate_authority(result)
        assert score < 0.7

    def test_calculate_freshness(self):
        ranker = SearchRanker()
        result = SearchResultItem(
            title="Test 2024",
            snippet="Published on Jan 15, 2024",
        )
        score = ranker.calculate_freshness(result)
        assert score >= 0.5

    def test_rank_results(self):
        ranker = SearchRanker()
        results = [
            SearchResultItem(title="Python Tutorial", url="https://github.com/python", rank=1),
            SearchResultItem(title="Cooking", url="https://unknown.com", rank=2),
        ]
        ranked = ranker.rank_results(results, "python tutorial")
        assert ranked[0].title == "Python Tutorial"
        assert ranked[0].final_score > ranked[1].final_score

    def test_ensure_diversity(self):
        ranker = SearchRanker()
        results = [
            SearchResultItem(title="Result 1", url="https://example.com/page1"),
            SearchResultItem(title="Result 2", url="https://example.com/page2"),
            SearchResultItem(title="Result 3", url="https://example.com/page3"),
            SearchResultItem(title="Result 4", url="https://other.com/page1"),
        ]
        diversified = ranker.ensure_diversity(results, max_per_domain=2)
        assert len(diversified) == 3  # 2 from example.com + 1 from other.com


class TestSearchOptimizer:
    """Test SearchOptimizer class."""

    def test_creation(self):
        optimizer = SearchOptimizer(backends=["bing", "duckduckgo"])
        assert optimizer.backends == ["bing", "duckduckgo"]
        assert optimizer.max_results == 10

    def test_search_with_mock_fn(self):
        optimizer = SearchOptimizer(backends=["mock1", "mock2"])

        def mock_search(backend, query, max_results):
            return [
                {"title": f"{backend} Result 1", "url": "https://example.com/1", "snippet": "Test"},
                {"title": f"{backend} Result 2", "url": "https://example.com/2", "snippet": "Test"},
            ]

        response = optimizer.search("test query", search_fn=mock_search)
        assert response.total_results > 0
        assert len(response.backends_queried) == 2
        assert response.response_time_ms > 0

    def test_search_cache(self):
        optimizer = SearchOptimizer(backends=["mock"], enable_cache=True)

        call_count = 0

        def mock_search(backend, query, max_results):
            nonlocal call_count
            call_count += 1
            return [{"title": "Test", "url": "https://example.com", "snippet": "Test"}]

        # First search
        response1 = optimizer.search("cache test", search_fn=mock_search)
        assert response1.cache_hit is False
        assert call_count == 1

        # Second search (should hit cache)
        response2 = optimizer.search("cache test", search_fn=mock_search)
        assert response2.cache_hit is True
        assert call_count == 1  # Should not call search_fn again

    def test_query_rewrite(self):
        optimizer = SearchOptimizer(backends=["mock"], enable_query_rewrite=True)

        def mock_search(backend, query, max_results):
            return [{"title": query, "url": "https://example.com", "snippet": "Test"}]

        response = optimizer.search("learn js", search_fn=mock_search)
        assert response.query_rewritten is True
        assert "javascript" in response.rewritten_query

    def test_get_stats(self):
        optimizer = SearchOptimizer(backends=["bing", "duckduckgo"])
        stats = optimizer.get_stats()
        assert "backends" in stats
        assert "cache_size" in stats
        assert stats["backends"] == ["bing", "duckduckgo"]


class TestConvenienceFunction:
    """Test optimized_search convenience function."""

    def test_optimized_search(self):
        def mock_search(backend, query, max_results):
            return [{"title": "Test", "url": "https://example.com", "snippet": "Test"}]

        response = optimized_search("test", backends=["mock"], search_fn=mock_search)
        assert isinstance(response, SearchResponse)
        assert response.total_results > 0
