"""Global pytest configuration and fixtures for webscout-mcp tests.

Provides shared fixtures, test configuration, and integration/performance test setup.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ============ Test Configuration ============


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: mark end-to-end network tests (skipped in CI)")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "performance: marks tests as performance benchmarks")
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "network: marks tests that require network access")


def pytest_collection_modifyitems(config, items):
    """Modify test items to add markers based on test names."""
    for item in items:
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        if "benchmark" in item.nodeid or "performance" in item.nodeid:
            item.add_marker(pytest.mark.performance)
        if "network" in item.nodeid:
            item.add_marker(pytest.mark.network)


# ============ Common Fixtures ============


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    dir_path = tempfile.mkdtemp(prefix="webscout_test_")
    yield dir_path
    shutil.rmtree(dir_path, ignore_errors=True)


@pytest.fixture
def temp_file():
    """Create a temporary file for test data."""
    fd, file_path = tempfile.mkstemp(prefix="webscout_test_", suffix=".txt")
    os.close(fd)
    yield file_path
    if os.path.exists(file_path):
        os.unlink(file_path)


@pytest.fixture
def sample_html():
    """Sample HTML for testing content extraction."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Test Page - Python Programming</title>
        <meta name="description" content="A test page about Python programming">
        <meta name="author" content="Test Author">
    </head>
    <body>
        <header>
            <nav>
                <a href="/">Home</a>
                <a href="/about">About</a>
                <a href="/contact">Contact</a>
            </nav>
        </header>
        <main>
            <article>
                <h1>Python Programming Tutorial</h1>
                <p>Python is a popular programming language known for its simplicity and readability.</p>
                <p>It is widely used in web development, data science, artificial intelligence, and many other fields.</p>
                <h2>Getting Started</h2>
                <p>To get started with Python, you need to install it on your computer.</p>
                <ul>
                    <li>Download Python from python.org</li>
                    <li>Run the installer</li>
                    <li>Verify installation with python --version</li>
                </ul>
                <h2>Basic Syntax</h2>
                <p>Python uses indentation to define code blocks.</p>
                <pre><code>def hello():
    print("Hello, World!")</code></pre>
            </article>
            <aside>
                <h3>Related Articles</h3>
                <ul>
                    <li><a href="/python-tips">Python Tips</a></li>
                    <li><a href="/python-libraries">Python Libraries</a></li>
                </ul>
            </aside>
        </main>
        <footer>
            <p>&copy; 2024 Test Site. All rights reserved.</p>
            <p><a href="/privacy">Privacy Policy</a> | <a href="/terms">Terms of Service</a></p>
        </footer>
    </body>
    </html>
    """


@pytest.fixture
def sample_sitemap_xml():
    """Sample sitemap XML for testing."""
    return """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url>
            <loc>https://example.com/page1</loc>
            <lastmod>2024-01-15</lastmod>
            <changefreq>weekly</changefreq>
            <priority>0.8</priority>
        </url>
        <url>
            <loc>https://example.com/page2</loc>
            <lastmod>2024-01-20</lastmod>
            <priority>0.5</priority>
        </url>
    </urlset>
    """


@pytest.fixture
def sample_json():
    """Provide sample JSON data for testing."""
    return {
        "name": "webscout-mcp",
        "version": "0.4.0",
        "description": "AI-powered web search and content extraction",
        "features": ["search", "fetch", "crawl", "summarize", "extract"],
        "config": {
            "cache_ttl": 7200,
            "max_retries": 3,
            "timeout": 15.0,
        },
        "stats": {
            "searches": 1000,
            "fetches": 500,
            "crawls": 100,
        },
    }


@pytest.fixture
def sample_text():
    """Provide sample text content for testing."""
    return """Python is a high-level, general-purpose programming language. Its design philosophy emphasizes code readability with the use of significant indentation.

Python is dynamically typed and garbage-collected. It supports multiple programming paradigms, including structured, object-oriented, and functional programming.

Python was created by Guido van Rossum and first released in 1991. Python 3.0 was released in 2008 and was a major revision of the language that is not completely backward-compatible.

Python consistently ranks as one of the most popular programming languages. It is used in web development, data science, artificial intelligence, scientific computing, and many other fields."""


@pytest.fixture
def sample_urls():
    """Provide sample URLs for testing."""
    return [
        "https://example.com/page1",
        "https://example.com/page2",
        "https://example.com/page3",
        "https://other.com/article1",
        "https://other.com/article2",
    ]


@pytest.fixture
def mock_search_results():
    """Provide mock search results for testing."""
    return [
        {
            "title": "Python Programming Tutorial",
            "url": "https://example.com/python-tutorial",
            "snippet": "Learn Python programming from scratch with this comprehensive tutorial.",
            "source": "bing",
            "rank": 1,
        },
        {
            "title": "Python Official Documentation",
            "url": "https://docs.python.org/3/",
            "snippet": "The official Python documentation, including tutorials, library reference, and language reference.",
            "source": "bing",
            "rank": 2,
        },
        {
            "title": "Real Python - Python Tutorials",
            "url": "https://realpython.com",
            "snippet": "In-depth Python tutorials and articles for developers of all skill levels.",
            "source": "duckduckgo",
            "rank": 1,
        },
    ]


# ============ Integration Test Fixtures ============


@pytest.fixture
def integration_test_config():
    """Provide configuration for integration tests."""
    return {
        "test_mode": True,
        "cache_enabled": False,
        "rate_limit_enabled": False,
        "log_level": "DEBUG",
        "request_timeout": 5.0,
        "max_retries": 1,
    }


@pytest.fixture
def test_environment(integration_test_config, temp_dir):
    """Set up a complete test environment for integration tests."""
    env = {
        "config": integration_test_config,
        "temp_dir": temp_dir,
        "cache_dir": os.path.join(temp_dir, "cache"),
        "data_dir": os.path.join(temp_dir, "data"),
        "log_dir": os.path.join(temp_dir, "logs"),
    }

    # Create directories
    os.makedirs(env["cache_dir"], exist_ok=True)
    os.makedirs(env["data_dir"], exist_ok=True)
    os.makedirs(env["log_dir"], exist_ok=True)

    # Set environment variables
    os.environ["WEBSCOUT_TEST_MODE"] = "true"
    os.environ["WEBSCOUT_CACHE_DIR"] = env["cache_dir"]
    os.environ["WEBSCOUT_DATA_DIR"] = env["data_dir"]

    yield env

    # Cleanup
    for key in ["WEBSCOUT_TEST_MODE", "WEBSCOUT_CACHE_DIR", "WEBSCOUT_DATA_DIR"]:
        os.environ.pop(key, None)


# ============ Performance Test Fixtures ============


@pytest.fixture
def performance_test_config():
    """Provide configuration for performance tests."""
    return {
        "iterations": 100,
        "warmup_iterations": 10,
        "threshold_ms": 1000,
        "sample_size": 1000,
    }


@pytest.fixture
def large_text_sample():
    """Provide a large text sample for performance testing."""
    base_text = "Python is a popular programming language. " * 100
    return base_text


@pytest.fixture
def large_html_sample(sample_html):
    """Provide a large HTML sample for performance testing."""
    return sample_html * 10


# ============ Utility Fixtures ============


@pytest.fixture
def timer():
    """Provide a timer fixture for measuring execution time."""
    import time

    class Timer:
        def __init__(self):
            self.start_time = None
            self.end_time = None
            self.duration = None

        def __enter__(self):
            self.start_time = time.perf_counter()
            return self

        def __exit__(self, *args):
            self.end_time = time.perf_counter()
            self.duration = (self.end_time - self.start_time) * 1000  # ms

        @property
        def duration_ms(self):
            return self.duration

    return Timer()


@pytest.fixture
def memory_tracker():
    """Provide a memory tracker fixture."""
    import tracemalloc

    class MemoryTracker:
        def __init__(self):
            self.start_snapshot = None
            self.end_snapshot = None

        def __enter__(self):
            tracemalloc.start()
            self.start_snapshot = tracemalloc.take_snapshot()
            return self

        def __exit__(self, *args):
            self.end_snapshot = tracemalloc.take_snapshot()
            tracemalloc.stop()

        @property
        def memory_diff(self):
            if not self.start_snapshot or not self.end_snapshot:
                return 0
            stats = self.end_snapshot.compare_to(self.start_snapshot, "lineno")
            return sum(stat.size_diff for stat in stats)

    return MemoryTracker()
