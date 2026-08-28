"""
Advanced Features Examples for webscout-mcp

This file demonstrates advanced features:
- Search optimization
- Content extraction optimization
- RAG optimization
- AI optimization
- Security features
- Health checks

Run with: python examples/advanced_examples.py
"""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def example_search_optimizer():
    """Example: Search optimizer with caching and concurrent search."""
    print("=" * 60)
    print("Example: Search Optimizer")
    print("=" * 60)

    from webscout_mcp.search_optimizer import SearchOptimizer

    # Create optimizer with all features enabled
    optimizer = SearchOptimizer(
        backends=["bing", "duckduckgo"],
        enable_cache=True,
        cache_ttl=3600,
        enable_concurrent=True,
        enable_deduplication=True,
        enable_intelligent_ranking=True,
    )

    # Mock search function for demonstration
    def mock_search(backend, query, max_results):
        return [
            {
                "title": f"{backend} Result {i} for {query}",
                "url": f"https://example.com/{backend}/{i}",
                "snippet": f"Snippet {i} about {query}",
                "source": backend,
                "rank": i + 1,
            }
            for i in range(5)
        ]

    # First search (cache miss)
    result1 = optimizer.search("python tutorial", search_fn=mock_search)
    print(f"\nFirst search (cache miss):")
    print(f"  Total results: {result1.total_results}")
    print(f"  Search time: {result1.search_time_ms:.2f}ms")
    print(f"  Cache hit: {result1.cache_hit}")

    # Second search (cache hit)
    result2 = optimizer.search("python tutorial", search_fn=mock_search)
    print(f"\nSecond search (cache hit):")
    print(f"  Total results: {result2.total_results}")
    print(f"  Search time: {result2.search_time_ms:.2f}ms")
    print(f"  Cache hit: {result2.cache_hit}")

    print(f"\nTop 3 results:")
    for i, item in enumerate(result1.results[:3], 1):
        print(f"  {i}. {item.title} (relevance: {item.relevance_score:.2f})")


def example_content_extractor():
    """Example: Content extractor with multi-algorithm fusion."""
    print("\n" + "=" * 60)
    print("Example: Content Extractor Optimization")
    print("=" * 60)

    from webscout_mcp.content_extractor import ContentExtractor

    # Sample HTML
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Python Programming Guide</title>
        <meta name="description" content="Comprehensive Python programming guide">
        <meta name="author" content="Python Expert">
    </head>
    <body>
        <header><nav><a href="/">Home</a></nav></header>
        <main>
            <article>
                <h1>Python Programming Guide</h1>
                <p>Python is a versatile programming language used in many fields.</p>
                <p>It is known for its simplicity and readability.</p>
                <h2>Getting Started</h2>
                <p>Install Python from the official website and start coding.</p>
                <ul><li>Download Python</li><li>Install IDE</li><li>Write code</li></ul>
            </article>
        </main>
        <footer><p>Copyright 2024</p></footer>
    </body>
    </html>
    """

    # Create extractor with all features
    extractor = ContentExtractor(
        enable_multi_algorithm=True,
        enable_quality_assessment=True,
        enable_language_detection=True,
    )

    # Extract content
    content = extractor.extract(html, url="https://example.com/python-guide")

    print(f"\nExtracted content:")
    print(f"  Title: {content.title}")
    print(f"  Author: {content.author}")
    print(f"  Language: {content.language}")
    print(f"  Word count: {content.word_count}")
    print(f"  Quality score: {content.quality_score:.2f}")
    print(f"  Algorithm used: {content.algorithm_used}")
    print(f"\n  Content preview:\n  {content.content[:200]}...")


def example_rag_optimizer():
    """Example: RAG optimizer with semantic chunking and query rewriting."""
    print("\n" + "=" * 60)
    print("Example: RAG Optimizer")
    print("=" * 60)

    from webscout_mcp.rag_optimizer import RAGOptimizer

    # Sample documents
    documents = [
        """Python is a high-level programming language. It was created by Guido van Rossum
        and first released in 1991. Python emphasizes code readability and allows programmers
        to express concepts in fewer lines of code.""",
        """JavaScript is a programming language that enables interactive web pages. It is
        an essential part of web applications. JavaScript is high-level, often just-in-time
        compiled, and multi-paradigm.""",
        """Machine learning is a subset of artificial intelligence. It provides systems the
        ability to automatically learn and improve from experience without being explicitly
        programmed. Machine learning focuses on the development of computer programs.""",
    ]

    # Create RAG optimizer
    optimizer = RAGOptimizer(
        max_chunk_size=200,
        chunk_overlap=20,
        enable_semantic_chunking=True,
        enable_query_rewrite=True,
        enable_context_compression=True,
    )

    # Prepare documents (semantic chunking)
    chunks = optimizer.prepare_documents(documents)
    print(f"\nPrepared {len(chunks)} chunks from {len(documents)} documents")
    for i, chunk in enumerate(chunks[:3]):
        print(f"  Chunk {i+1}: {len(chunk.text)} chars, metadata: {chunk.metadata}")

    # Retrieve relevant chunks
    query = "py programming language"
    result = optimizer.retrieve(query, chunks, top_k=2)

    print(f"\nQuery: '{query}'")
    print(f"Retrieved {len(result.chunks)} chunks")
    print(f"Retrieval score: {result.retrieval_score:.4f}")
    if result.compressed_context:
        print(f"Compressed context: {result.compressed_context[:150]}...")


def example_security():
    """Example: Security features (SSRF protection, input validation, rate limiting)."""
    print("\n" + "=" * 60)
    print("Example: Security Features")
    print("=" * 60)

    from webscout_mcp.security import SecurityManager, SensitiveDataFilter, SSRFProtector

    # SSRF Protection
    print("\n1. SSRF Protection:")
    protector = SSRFProtector(dns_resolution=False)

    test_urls = [
        "https://example.com/page",
        "http://localhost/admin",
        "file:///etc/passwd",
        "http://169.254.169.254/latest/meta-data/",
    ]

    for url in test_urls:
        is_safe, reason = protector.validate_url(url)
        status = "SAFE" if is_safe else "BLOCKED"
        print(f"  [{status}] {url}")
        if not is_safe:
            print(f"         Reason: {reason}")

    # Sensitive Data Filtering
    print("\n2. Sensitive Data Filtering:")
    filter_obj = SensitiveDataFilter()
    sensitive_text = "User API key: abc123def456, password: secret123, email: user@example.com"
    filtered = filter_obj.mask(sensitive_text)
    print(f"  Original: {sensitive_text}")
    print(f"  Filtered: {filtered}")

    # Security Manager
    print("\n3. Security Manager:")
    security = SecurityManager(
        enable_ssrf_protection=True,
        enable_input_validation=True,
        enable_rate_limiting=True,
        enable_sensitive_data_filtering=True,
    )
    print(f"  SSRF protection: {security.ssrf_protection_enabled}")
    print(f"  Input validation: {security.input_validation_enabled}")
    print(f"  Rate limiting: {security.rate_limiting_enabled}")
    print(f"  Sensitive data filtering: {security.sensitive_data_filtering_enabled}")


def example_health_check():
    """Example: Health checks and system monitoring."""
    print("\n" + "=" * 60)
    print("Example: Health Checks and System Monitoring")
    print("=" * 60)

    from webscout_mcp.health import HealthChecker, SystemMonitor, get_health_report

    # Create health checker
    checker = HealthChecker(version="0.4.0")

    # Register custom checks
    checker.register_check("custom_check", lambda: (True, "Custom check passed"))
    checker.register_dependency("cache", lambda: True)
    checker.register_dependency("database", lambda: True)

    # Check liveness
    liveness = checker.check_liveness()
    print(f"\nLiveness check:")
    print(f"  Status: {liveness.status}")
    print(f"  Version: {liveness.version}")
    print(f"  Uptime: {liveness.uptime_seconds:.1f}s")

    # Check readiness
    readiness = checker.check_readiness()
    print(f"\nReadiness check:")
    print(f"  Status: {readiness.status}")
    for check_name, check_result in readiness.checks.items():
        print(f"    {check_name}: {check_result.status}")

    # System monitor
    monitor = SystemMonitor()
    metrics = monitor.collect_metrics()
    print(f"\nSystem metrics:")
    print(f"  Platform: {metrics.platform}")
    print(f"  Python version: {metrics.python_version}")
    print(f"  CPU count: {metrics.cpu_count}")
    print(f"  Timestamp: {metrics.timestamp}")

    # Full health report
    report = get_health_report()
    print(f"\nFull health report:")
    print(f"  Overall status: {report['health']['status']}")
    print(f"  Service status: {report['service']['status']}")


def main():
    """Run all advanced examples."""
    print("\n" + "=" * 60)
    print("webscout-mcp Advanced Features Examples")
    print("=" * 60 + "\n")

    examples = [
        ("Search Optimizer", example_search_optimizer),
        ("Content Extractor", example_content_extractor),
        ("RAG Optimizer", example_rag_optimizer),
        ("Security Features", example_security),
        ("Health Checks", example_health_check),
    ]

    for name, example_func in examples:
        try:
            example_func()
        except Exception as e:
            print(f"\n[ERROR] Example '{name}' failed: {e}")
            import traceback

            traceback.print_exc()
        print()

    print("=" * 60)
    print("All advanced examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
