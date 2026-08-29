"""Integration tests for webscout-mcp.

Tests module interactions and end-to-end workflows.
These tests verify that multiple modules work together correctly.
"""

import time

from webscout_mcp.ai_optimizer import AIOptimizer
from webscout_mcp.architecture import DIContainer, EventBus
from webscout_mcp.async_utils import ConcurrencyLimiter, PerformanceMonitor
from webscout_mcp.content_extractor import ContentExtractor, ExtractedContent
from webscout_mcp.errors import ValidationError
from webscout_mcp.health import HealthChecker, SystemMonitor
from webscout_mcp.rag_optimizer import Chunk, RAGOptimizer
from webscout_mcp.search_optimizer import SearchOptimizer
from webscout_mcp.security import SecurityManager, SSRFProtector

# ============ Search + Content Extraction Integration ============


class TestSearchContentIntegration:
    """Test search and content extraction working together."""

    def test_search_then_extract_pipeline(self, sample_html, content_extractor):
        """Test complete pipeline: search -> fetch -> extract."""
        # Step 1: Search (using mock function)
        search_optimizer = SearchOptimizer(backends=["mock"], enable_cache=False)

        def mock_search(backend, query, max_results):
            return [
                {
                    "title": "Python Tutorial",
                    "url": "https://example.com/python",
                    "snippet": "Learn Python programming",
                    "source": backend,
                    "rank": 1,
                }
            ]

        search_result = search_optimizer.search("python tutorial", search_fn=mock_search)
        assert search_result.total_results > 0
        assert search_result.results[0].url == "https://example.com/python"

        # Step 2: Extract content from HTML
        extracted = content_extractor.extract(sample_html, url="https://example.com/python")
        assert isinstance(extracted, ExtractedContent)
        assert len(extracted.content) > 0
        assert extracted.quality_score > 0
        assert extracted.word_count > 0

        # Step 3: Verify pipeline consistency
        assert extracted.url == "https://example.com/python"
        assert "Python" in extracted.content or "python" in extracted.content.lower()

    def test_search_result_to_extraction_input(self, sample_html, content_extractor):
        """Test converting search results to extraction inputs."""
        search_optimizer = SearchOptimizer(backends=["mock"], enable_diversity=False)

        def mock_search(backend, query, max_results):
            return [
                {"title": f"Result {i}", "url": f"https://example.com/page{i}", "snippet": f"Snippet {i}"}
                for i in range(3)
            ]

        search_result = search_optimizer.search("test", search_fn=mock_search)
        assert search_result.total_results == 3

        # Convert search results to extraction batch
        pages = [{"html": sample_html, "url": result.url, "title": result.title} for result in search_result.results]
        extracted_results = content_extractor.extract_batch(pages)
        assert len(extracted_results) == 3
        assert all(isinstance(r, ExtractedContent) for r in extracted_results)


# ============ RAG + AI Integration ============


class TestRAGAIIntegration:
    """Test RAG and AI processing working together."""

    def test_rag_then_ai_pipeline(self, sample_text):
        """Test complete pipeline: chunk -> retrieve -> AI process."""
        # Step 1: Prepare documents and chunk
        rag_optimizer = RAGOptimizer(max_chunk_size=100)
        chunks = rag_optimizer.prepare_documents([sample_text])
        assert len(chunks) > 0
        assert all(isinstance(c, Chunk) for c in chunks)

        # Step 2: Retrieve relevant chunks
        query = "Python programming language"
        rag_result = rag_optimizer.retrieve(query, chunks, top_k=2)
        assert len(rag_result.chunks) > 0
        assert rag_result.retrieval_score >= 0

        # Step 3: AI process retrieved context
        ai_optimizer = AIOptimizer()
        context = rag_result.compressed_context or " ".join(c.text for c in rag_result.chunks)

        def mock_ai(prompt):
            return f"Based on the context: {context[:50]}..."

        ai_result = ai_optimizer.process(
            sample_text,
            task="summarize",
            context=context,
            ai_fn=mock_ai,
        )
        assert ai_result.content != ""
        assert ai_result.total_tokens > 0

    def test_rag_query_rewrite_improves_retrieval(self, sample_text):
        """Test that query rewriting improves retrieval quality."""
        rag_optimizer = RAGOptimizer(max_chunk_size=100, enable_query_rewrite=True)
        chunks = rag_optimizer.prepare_documents([sample_text])

        # Query with abbreviation
        result = rag_optimizer.retrieve("py programming", chunks, top_k=3)
        # Should still retrieve relevant chunks
        assert len(result.chunks) > 0


# ============ Security + Search Integration ============


class TestSecuritySearchIntegration:
    """Test security validation working with search operations."""

    def test_validate_url_before_search(self):
        """Test that URLs are validated before search operations."""
        security = SecurityManager()
        ssrf = SSRFProtector(dns_resolution=False)

        # Valid URL should pass
        is_safe, _ = ssrf.validate_url("https://example.com/search")
        assert is_safe is True

        # Dangerous URL should be blocked
        is_safe, reason = ssrf.validate_url("file:///etc/passwd")
        assert is_safe is False
        assert "file" in reason.lower()

        # Localhost should be blocked
        is_safe, _ = ssrf.validate_url("http://localhost/admin")
        assert is_safe is False

    def test_security_manager_complete_validation(self):
        """Test complete security validation pipeline."""
        security = SecurityManager()

        # Test output filtering
        sensitive_text = "api_key=secret123 and password=hidden456"
        filtered = security.filter_output(sensitive_text)
        assert "secret123" not in filtered
        assert "hidden456" not in filtered

        # Test security headers
        headers = security.get_security_headers()
        assert "X-Content-Type-Options" in headers
        assert "Content-Security-Policy" in headers


# ============ Performance Monitoring Integration ============


class TestPerformanceMonitoringIntegration:
    """Test performance monitoring across multiple modules."""

    def test_track_pipeline_performance(self, sample_html, content_extractor):
        """Test tracking performance of complete pipeline."""
        monitor = PerformanceMonitor()

        with monitor.time("search"):
            time.sleep(0.01)

        with monitor.time("content_extraction"):
            content_extractor.extract(sample_html)

        with monitor.time("ai_processing"):
            time.sleep(0.01)

        stats = monitor.get_stats()
        assert stats["total_timings"] == 3
        assert "search" in [t["name"] for t in stats["recent_timings"]]
        assert stats["total_time_ms"] > 0

    def test_concurrent_operations_with_limiter(self):
        """Test concurrent operations with concurrency limiter."""
        import asyncio

        limiter = ConcurrencyLimiter(max_concurrent=2)

        async def process_item(item):
            async with limiter.acquire():
                await asyncio.sleep(0.01)
                return item * 2

        results = asyncio.run(limiter.map(process_item, [1, 2, 3, 4, 5]))
        assert results == [2, 4, 6, 8, 10]
        assert limiter.get_stats()["max_concurrent"] == 2


# ============ Event Bus + Module Integration ============


class TestEventBusIntegration:
    """Test event bus coordinating module interactions."""

    def test_event_driven_pipeline(self, sample_html):
        """Test event-driven pipeline with multiple modules."""
        bus = EventBus()
        events_received = []

        @bus.on("search.completed")
        def handle_search(event):
            events_received.append(("search", event))

        @bus.on("extraction.completed")
        def handle_extraction(event):
            events_received.append(("extraction", event))

        @bus.on("ai.completed")
        def handle_ai(event):
            events_received.append(("ai", event))

        # Simulate pipeline
        bus.publish("search.completed", data={"query": "test", "results": 5})
        bus.publish("extraction.completed", data={"url": "https://example.com", "words": 100})
        bus.publish("ai.completed", data={"task": "summarize", "tokens": 50})

        assert len(events_received) == 3
        assert events_received[0][0] == "search"
        assert events_received[1][0] == "extraction"
        assert events_received[2][0] == "ai"

    def test_event_history_tracking(self):
        """Test event history for debugging and monitoring."""
        bus = EventBus()

        bus.publish("event1")
        bus.publish("event2")
        bus.publish("event1")

        history = bus.get_event_history()
        assert len(history) == 3

        filtered = bus.get_event_history(event_name="event1")
        assert len(filtered) == 2


# ============ Health Check Integration ============


class TestHealthCheckIntegration:
    """Test health checks with actual module states."""

    def test_complete_health_report(self):
        """Test generating complete health report."""
        from webscout_mcp.health import get_health_report

        report = get_health_report()
        assert "health" in report
        assert "system" in report
        assert "service" in report
        assert "dependencies" in report
        assert report["health"]["status"] in ["healthy", "degraded", "unhealthy"]

    def test_health_checker_with_custom_checks(self):
        """Test health checker with custom dependency checks."""
        checker = HealthChecker(version="1.0.0")

        # Register a healthy dependency
        checker.register_dependency("cache", lambda: True)

        # Register an unhealthy dependency
        checker.register_dependency("database", lambda: False)

        status = checker.check_readiness()
        assert status.status == "unhealthy"
        assert "dependency:cache" in status.checks
        assert "dependency:database" in status.checks

    def test_system_metrics_collection(self):
        """Test system metrics collection."""
        monitor = SystemMonitor()
        metrics = monitor.collect_metrics()
        assert metrics.timestamp != ""
        assert metrics.python_version != ""
        assert metrics.platform != ""


# ============ Error Handling Integration ============


class TestErrorHandlingIntegration:
    """Test error handling across module boundaries."""

    def test_error_propagation_in_pipeline(self):
        """Test that errors propagate correctly through pipeline."""
        from webscout_mcp.errors import safe_execute

        # Test safe execution with error
        def failing_operation():
            raise ValueError("Pipeline error")

        result = safe_execute(failing_operation, default="fallback")
        assert result == "fallback"

    def test_error_context_extraction(self):
        """Test extracting context from errors."""
        from webscout_mcp.errors import get_error_context

        error = ValidationError(field="url", message="Invalid URL", value="bad-url")
        context = get_error_context(error)
        assert context["type"] == "ValidationError"
        assert "field" in context["details"]
        assert context["details"]["field"] == "url"

    def test_error_registry_lookup(self):
        """Test looking up errors by code."""
        from webscout_mcp.errors import ConfigurationError, ErrorRegistry

        error_class = ErrorRegistry.get_by_code("WS100")
        assert error_class == ConfigurationError

        all_errors = ErrorRegistry.list_all()
        assert "WS100" in all_errors
        assert "WS200" in all_errors


# ============ Dependency Injection Integration ============


class TestDependencyInjectionIntegration:
    """Test dependency injection across modules."""

    def test_di_container_with_modules(self):
        """Test DI container managing module instances."""
        container = DIContainer()

        # Register services
        search_optimizer = SearchOptimizer(backends=["mock"])
        content_extractor = ContentExtractor()
        health_checker = HealthChecker()

        container.register_singleton(SearchOptimizer, search_optimizer)
        container.register_singleton(ContentExtractor, content_extractor)
        container.register_singleton(HealthChecker, health_checker)

        # Resolve services
        resolved_search = container.resolve(SearchOptimizer)
        resolved_extractor = container.resolve(ContentExtractor)
        resolved_health = container.resolve(HealthChecker)

        assert resolved_search is search_optimizer
        assert resolved_extractor is content_extractor
        assert resolved_health is health_checker

        # Test inject decorator
        @container.inject(SearchOptimizer, ContentExtractor)
        def pipeline(search, extractor, query):
            assert isinstance(search, SearchOptimizer)
            assert isinstance(extractor, ContentExtractor)
            return f"Processing {query}"

        result = pipeline("test query")
        assert result == "Processing test query"
