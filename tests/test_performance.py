"""Performance benchmark tests for webscout-mcp.

Tests performance characteristics of core modules.
These tests establish performance baselines and detect regressions.
"""

import statistics
import time

import pytest

from webscout_mcp.ai_optimizer import AIOptimizer
from webscout_mcp.architecture import EventBus
from webscout_mcp.async_utils import PerformanceMonitor
from webscout_mcp.content_extractor import ContentExtractor
from webscout_mcp.errors import safe_execute
from webscout_mcp.health import SystemMonitor
from webscout_mcp.rag_optimizer import RAGOptimizer
from webscout_mcp.search_optimizer import SearchOptimizer
from webscout_mcp.security import InputValidator, SensitiveDataFilter

# ============ Performance Test Configuration ============

PERF_TEST_ITERATIONS = 50
PERF_WARMUP_ITERATIONS = 5
PERF_THRESHOLD_MS = 1000  # 1 second threshold for most operations


# ============ Helper Functions ============


def benchmark(func, iterations=PERF_TEST_ITERATIONS, warmup=PERF_WARMUP_ITERATIONS):
    """Benchmark a function and return statistics.

    Args:
        func: Function to benchmark.
        iterations: Number of iterations.
        warmup: Number of warmup iterations.

    Returns:
        Dictionary with performance statistics.
    """
    # Warmup
    for _ in range(warmup):
        func()

    # Benchmark
    durations = []
    for _ in range(iterations):
        start = time.perf_counter()
        func()
        end = time.perf_counter()
        durations.append((end - start) * 1000)  # ms

    return {
        "iterations": iterations,
        "min_ms": min(durations),
        "max_ms": max(durations),
        "mean_ms": statistics.mean(durations),
        "median_ms": statistics.median(durations),
        "stdev_ms": statistics.stdev(durations) if len(durations) > 1 else 0,
        "p95_ms": sorted(durations)[int(len(durations) * 0.95)],
        "p99_ms": sorted(durations)[int(len(durations) * 0.99)],
        "total_ms": sum(durations),
        "throughput_per_sec": iterations / (sum(durations) / 1000),
    }


def assert_performance(stats, threshold_ms=PERF_THRESHOLD_MS):
    """Assert that performance is within acceptable thresholds.

    Args:
        stats: Benchmark statistics dictionary.
        threshold_ms: Maximum acceptable mean duration in ms.
    """
    assert (
        stats["mean_ms"] < threshold_ms
    ), f"Performance regression: mean {stats['mean_ms']:.2f}ms > {threshold_ms}ms threshold"
    assert stats["p99_ms"] < threshold_ms * 3, f"P99 too high: {stats['p99_ms']:.2f}ms"


# ============ Search Performance Tests ============


class TestSearchPerformance:
    """Performance tests for search optimizer."""

    @pytest.mark.performance
    def test_search_optimizer_performance(self):
        """Benchmark search optimizer with mock backend."""
        optimizer = SearchOptimizer(backends=["mock"], enable_cache=False)

        def mock_search(backend, query, max_results):
            return [
                {"title": f"Result {i}", "url": f"https://example.com/page{i}", "snippet": f"Snippet {i}"}
                for i in range(10)
            ]

        def operation():
            optimizer.search("test query", search_fn=mock_search)

        stats = benchmark(operation, iterations=100, warmup=10)
        assert_performance(stats, threshold_ms=50)
        assert stats["throughput_per_sec"] > 100

    @pytest.mark.performance
    def test_search_caching_performance(self):
        """Benchmark search with caching enabled (should be faster on repeat)."""
        optimizer = SearchOptimizer(backends=["mock"], enable_cache=True, cache_ttl=60)

        def mock_search(backend, query, max_results):
            time.sleep(0.001)  # Simulate network delay
            return [{"title": "Test", "url": "https://example.com", "snippet": "Test"}]

        # First call (cache miss)
        start = time.perf_counter()
        optimizer.search("cached query", search_fn=mock_search)
        first_duration = (time.perf_counter() - start) * 1000

        # Second call (cache hit)
        start = time.perf_counter()
        optimizer.search("cached query", search_fn=mock_search)
        second_duration = (time.perf_counter() - start) * 1000

        # Cache hit should be significantly faster
        assert (
            second_duration < first_duration * 0.5
        ), f"Cache not effective: first={first_duration:.2f}ms, second={second_duration:.2f}ms"


# ============ Content Extraction Performance Tests ============


class TestContentExtractionPerformance:
    """Performance tests for content extractor."""

    @pytest.mark.performance
    def test_content_extractor_performance(self, sample_html):
        """Benchmark content extraction."""
        extractor = ContentExtractor()

        def operation():
            extractor.extract(sample_html, url="https://example.com")

        stats = benchmark(operation, iterations=50, warmup=5)
        assert_performance(stats, threshold_ms=100)

    @pytest.mark.performance
    def test_large_html_extraction_performance(self, large_html_sample):
        """Benchmark extraction on large HTML content."""
        extractor = ContentExtractor()

        def operation():
            extractor.extract(large_html_sample, url="https://example.com/large")

        stats = benchmark(operation, iterations=20, warmup=3)
        assert_performance(stats, threshold_ms=500)


# ============ RAG Performance Tests ============


class TestRAGPerformance:
    """Performance tests for RAG optimizer."""

    @pytest.mark.performance
    def test_rag_chunking_performance(self, large_text_sample):
        """Benchmark text chunking."""
        optimizer = RAGOptimizer(max_chunk_size=200)

        def operation():
            optimizer.prepare_documents([large_text_sample])

        stats = benchmark(operation, iterations=50, warmup=5)
        assert_performance(stats, threshold_ms=50)

    @pytest.mark.performance
    def test_rag_retrieval_performance(self, sample_text):
        """Benchmark RAG retrieval."""
        optimizer = RAGOptimizer(max_chunk_size=100)
        chunks = optimizer.prepare_documents([sample_text])

        def operation():
            optimizer.retrieve("python programming", chunks, top_k=3)

        stats = benchmark(operation, iterations=100, warmup=10)
        assert_performance(stats, threshold_ms=20)


# ============ AI Processing Performance Tests ============


class TestAIPerformance:
    """Performance tests for AI optimizer."""

    @pytest.mark.performance
    def test_ai_processing_performance(self, sample_text):
        """Benchmark AI processing with mock AI."""
        optimizer = AIOptimizer(enable_validation=False)

        def mock_ai(prompt):
            return "Mock AI response"

        def operation():
            optimizer.process(sample_text, task="summarize", ai_fn=mock_ai)

        stats = benchmark(operation, iterations=100, warmup=10)
        assert_performance(stats, threshold_ms=10)

    @pytest.mark.performance
    def test_ai_with_validation_performance(self, sample_text):
        """Benchmark AI processing with output validation."""
        optimizer = AIOptimizer(enable_validation=True)

        def mock_ai(prompt):
            return '{"summary": "Test", "key_points": ["a", "b"]}'

        def operation():
            optimizer.process(sample_text, task="extract_entities", ai_fn=mock_ai)

        stats = benchmark(operation, iterations=50, warmup=5)
        assert_performance(stats, threshold_ms=20)


# ============ Security Performance Tests ============


class TestSecurityPerformance:
    """Performance tests for security module."""

    @pytest.mark.performance
    def test_sensitive_data_filter_performance(self):
        """Benchmark sensitive data filtering."""
        filter_obj = SensitiveDataFilter()
        text = "This is a test with api_key=secret123 and password=hidden456 and email test@example.com"

        def operation():
            filter_obj.mask(text)

        stats = benchmark(operation, iterations=500, warmup=50)
        assert_performance(stats, threshold_ms=5)
        assert stats["throughput_per_sec"] > 1000

    @pytest.mark.performance
    def test_input_validation_performance(self):
        """Benchmark input validation."""
        validator = InputValidator()

        def operation():
            validator.validate_url("https://example.com/path?query=value")

        stats = benchmark(operation, iterations=1000, warmup=100)
        assert_performance(stats, threshold_ms=1)
        assert stats["throughput_per_sec"] > 5000


# ============ Event Bus Performance Tests ============


class TestEventBusPerformance:
    """Performance tests for event bus."""

    @pytest.mark.performance
    def test_event_publish_performance(self):
        """Benchmark event publishing."""
        bus = EventBus()
        bus.subscribe("test.event", lambda e: None)

        def operation():
            bus.publish("test.event", data={"key": "value"})

        stats = benchmark(operation, iterations=1000, warmup=100)
        assert_performance(stats, threshold_ms=1)
        assert stats["throughput_per_sec"] > 1000

    @pytest.mark.performance
    def test_multiple_handlers_performance(self):
        """Benchmark event with multiple handlers."""
        bus = EventBus()
        for i in range(10):
            bus.subscribe(f"test.event", lambda e, i=i: None)

        def operation():
            bus.publish("test.event")

        stats = benchmark(operation, iterations=500, warmup=50)
        assert_performance(stats, threshold_ms=5)


# ============ System Monitor Performance Tests ============


class TestSystemMonitorPerformance:
    """Performance tests for system monitor."""

    @pytest.mark.performance
    def test_metrics_collection_performance(self):
        """Benchmark system metrics collection."""
        monitor = SystemMonitor()

        def operation():
            monitor.collect_metrics()

        stats = benchmark(operation, iterations=100, warmup=10)
        assert_performance(stats, threshold_ms=50)


# ============ Error Handling Performance Tests ============


class TestErrorHandlingPerformance:
    """Performance tests for error handling."""

    @pytest.mark.performance
    def test_safe_execute_performance(self):
        """Benchmark safe execution."""

        def success_func():
            return "success"

        def operation():
            safe_execute(success_func, default="fallback")

        stats = benchmark(operation, iterations=1000, warmup=100)
        assert_performance(stats, threshold_ms=1)
        assert stats["throughput_per_sec"] > 10000


# ============ Overall Pipeline Performance Tests ============


class TestOverallPipelinePerformance:
    """End-to-end pipeline performance tests."""

    @pytest.mark.performance
    @pytest.mark.slow
    def test_complete_pipeline_performance(self, sample_html, sample_text):
        """Benchmark complete pipeline: search -> extract -> RAG -> AI."""
        search_optimizer = SearchOptimizer(backends=["mock"], enable_cache=False)
        content_extractor = ContentExtractor()
        rag_optimizer = RAGOptimizer(max_chunk_size=100)
        ai_optimizer = AIOptimizer(enable_validation=False)

        def mock_search(backend, query, max_results):
            return [{"title": "Test", "url": "https://example.com", "snippet": "Test"}]

        def mock_ai(prompt):
            return "AI response"

        def complete_pipeline():
            # Step 1: Search
            search_result = search_optimizer.search("test query", search_fn=mock_search)

            # Step 2: Extract content
            extracted = content_extractor.extract(sample_html, url="https://example.com")

            # Step 3: RAG chunk and retrieve
            chunks = rag_optimizer.prepare_documents([sample_text])
            rag_result = rag_optimizer.retrieve("test", chunks, top_k=2)

            # Step 4: AI process
            ai_result = ai_optimizer.process(sample_text, task="summarize", ai_fn=mock_ai)

            return search_result, extracted, rag_result, ai_result

        stats = benchmark(complete_pipeline, iterations=20, warmup=3)
        assert_performance(stats, threshold_ms=500)
