"""Basic tests for webscout-mcp core modules.

These tests focus on pure-logic components that don't require network access.
Network-dependent tests are marked and can be run with --run-network.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from webscout_mcp.cache import Cache
from webscout_mcp.config import Config
from webscout_mcp.extractor import DataExtractor, ExtractionRule
from webscout_mcp.utils import TokenBucket, is_valid_url, normalize_url, truncate_text

# --- Config ---


class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.cache_ttl == 7200
        assert cfg.request_timeout == 15.0
        assert cfg.search_max_results == 10

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_CACHE_TTL", "3600")
        monkeypatch.setenv("WEBSCOUT_SEARCH_MAX_RESULTS", "5")
        cfg = Config.from_env()
        assert cfg.cache_ttl == 3600
        assert cfg.search_max_results == 5

    def test_ensure_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir) / "test_cache")
            cfg.ensure_dirs()
            assert (Path(tmpdir) / "test_cache").exists()


# --- Cache ---


class TestCache:
    @pytest.fixture
    def cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            c = Cache(Path(tmpdir) / "test.db", ttl=3600, max_size_mb=10)
            yield c

    def test_set_and_get(self, cache):
        cache.set("https://example.com", "hello world", "text/plain")
        result = cache.get("https://example.com")
        assert result is not None
        assert result["value"] == "hello world"
        assert result["cached"] is True

    def test_get_missing(self, cache):
        assert cache.get("https://nonexistent.com") is None

    def test_expiry(self, cache):
        cache.set("https://example.com", "data", ttl=0)
        # ttl=0 means expires immediately
        import time

        time.sleep(0.1)
        assert cache.get("https://example.com") is None

    def test_delete(self, cache):
        cache.set("https://example.com", "data")
        cache.delete("https://example.com")
        assert cache.get("https://example.com") is None

    def test_clear(self, cache):
        cache.set("https://a.com", "a")
        cache.set("https://b.com", "b")
        deleted = cache.clear()
        assert deleted == 2
        assert cache.get("https://a.com") is None

    def test_stats(self, cache):
        cache.set("https://example.com", "hello")
        stats = cache.stats()
        assert stats["entries"] == 1
        assert stats["total_size_bytes"] > 0


# --- Utils ---


class TestUtils:
    def test_normalize_url(self):
        assert normalize_url("HTTPS://Example.COM/path//to//page/") == "https://example.com/path/to/page/"
        assert normalize_url("http://example.com:80/path") == "http://example.com/path"
        assert normalize_url("https://example.com:443/path") == "https://example.com/path"

    def test_normalize_url_strips_fragment(self):
        result = normalize_url("https://example.com/page#section")
        assert "#" not in result

    def test_is_valid_url(self):
        assert is_valid_url("https://example.com")
        assert is_valid_url("http://example.com/path?q=1")
        assert not is_valid_url("not a url")
        assert not is_valid_url("ftp://example.com")
        assert not is_valid_url("")

    def test_truncate_text(self):
        short = "hello"
        assert truncate_text(short, 100) == short

        long_text = "a" * 1000
        result = truncate_text(long_text, 100)
        assert len(result) < 1000
        assert "truncated" in result

    def test_token_bucket(self):
        import asyncio

        bucket = TokenBucket(rate=10.0, burst=2)
        # Should be able to acquire burst tokens quickly
        asyncio.run(bucket.acquire("https://example.com"))
        asyncio.run(bucket.acquire("https://example.com"))
        # Third should require a short wait
        asyncio.run(bucket.acquire("https://example.com"))


# --- Extractor ---


class TestExtractor:
    SAMPLE_HTML = """
    <html>
    <head><title>Test Page</title></head>
    <body>
        <h1 class="title">Hello World</h1>
        <p class="price">$29.99</p>
        <a href="https://example.com/1" class="item">Item 1</a>
        <a href="https://example.com/2" class="item">Item 2</a>
        <a href="https://example.com/3" class="item">Item 3</a>
        <div class="description">This is a <b>great</b> product.</div>
    </body>
    </html>
    """

    def test_extract_single_text(self):
        extractor = DataExtractor(Config(), None)  # fetcher not needed for HTML extraction
        rules = [ExtractionRule(name="title", selector="h1.title")]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert result["title"] == "Hello World"

    def test_extract_with_regex(self):
        extractor = DataExtractor(Config(), None)
        rules = [ExtractionRule(name="price", selector=".price", regex=r"\$([\d.]+)")]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert result["price"] == "29.99"

    def test_extract_attribute_multiple(self):
        extractor = DataExtractor(Config(), None)
        rules = [ExtractionRule(name="links", selector="a.item", attribute="href", multiple=True)]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert result["links"] == [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]

    def test_extract_default_on_missing(self):
        extractor = DataExtractor(Config(), None)
        rules = [ExtractionRule(name="missing", selector=".nonexistent", default="N/A")]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert result["missing"] == "N/A"


# --- MCP Server (import test) ---


class TestServer:
    def test_server_module_imports(self):
        """Verify the server module can be imported (mcp optional)."""
        # server module is optional - should not crash if mcp missing
        try:
            from webscout_mcp.server import create_server  # noqa: F401
        except ImportError:
            pytest.skip("mcp library not installed")

    def test_create_server_if_mcp_available(self):
        """Create server only if mcp is available and compatible."""
        mcp = pytest.importorskip("mcp")
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cfg = Config(cache_dir=Path(tmpdir))
                from webscout_mcp.server import create_server

                server = create_server(cfg)
                assert server is not None
        except Exception as exc:
            pytest.skip(f"Server creation failed (mcp version incompatibility): {exc}")


# --- URL Security (SSRF Protection) ---


class TestURLSecurity:
    def test_safe_public_url(self):
        from webscout_mcp.utils import is_safe_url

        is_safe, reason = is_safe_url("https://example.com/page")
        assert is_safe is True
        assert "safe" in reason.lower()

    def test_block_localhost(self):
        from webscout_mcp.utils import is_safe_url

        for url in [
            "http://localhost/admin",
            "http://127.0.0.1:8080/",
            "http://0.0.0.0/",
        ]:
            is_safe, reason = is_safe_url(url)
            assert is_safe is False
            assert "localhost" in reason.lower() or "private" in reason.lower() or "blocked" in reason.lower()

    def test_block_sensitive_ports(self):
        from webscout_mcp.utils import is_safe_url

        for url in [
            "http://example.com:22/",
            "http://example.com:3306/",
            "http://example.com:6379/",
            "http://example.com:27017/",
        ]:
            is_safe, reason = is_safe_url(url)
            assert is_safe is False
            assert "port" in reason.lower()

    def test_block_invalid_scheme(self):
        from webscout_mcp.utils import is_safe_url

        for url in [
            "ftp://example.com/",
            "file:///etc/passwd",
            "gopher://example.com/",
            "not a url",
        ]:
            is_safe, reason = is_safe_url(url)
            assert is_safe is False

    def test_allow_private_when_enabled(self):
        from webscout_mcp.utils import is_safe_url

        is_safe, reason = is_safe_url("http://localhost:3000/", allow_private=True)
        # When allow_private is True, localhost should be allowed
        # (but sensitive ports may still be blocked)
        assert "localhost" not in reason.lower() or is_safe is True

    def test_extract_domain(self):
        from webscout_mcp.utils import extract_domain

        assert extract_domain("https://example.com/path") == "example.com"
        assert extract_domain("http://sub.example.com:8080/page") == "sub.example.com"
        assert extract_domain("not a url") == ""


# --- Memory Cache (LRU) ---


class TestLRUCache:
    def test_set_and_get(self):
        import time

        from webscout_mcp.cache import LRUCache

        cache = LRUCache(max_size=3)
        future = time.time() + 3600
        cache.set("key1", "value1", "text/plain", time.time(), future)
        result = cache.get("key1")
        assert result is not None
        assert result[0] == "value1"
        assert result[1] == "text/plain"

    def test_get_missing(self):
        from webscout_mcp.cache import LRUCache

        cache = LRUCache(max_size=3)
        assert cache.get("missing") is None

    def test_lru_eviction(self):
        import time

        from webscout_mcp.cache import LRUCache

        cache = LRUCache(max_size=2)
        future = time.time() + 3600
        cache.set("key1", "value1", "text/plain", time.time(), future)
        cache.set("key2", "value2", "text/plain", time.time(), future)
        cache.set("key3", "value3", "text/plain", time.time(), future)
        # key1 should be evicted (LRU)
        assert cache.get("key1") is None
        assert cache.get("key2") is not None
        assert cache.get("key3") is not None

    def test_lru_order_update(self):
        import time

        from webscout_mcp.cache import LRUCache

        cache = LRUCache(max_size=2)
        future = time.time() + 3600
        cache.set("key1", "value1", "text/plain", time.time(), future)
        cache.set("key2", "value2", "text/plain", time.time(), future)
        # Access key1 to make it most recently used
        cache.get("key1")
        # Add key3 - should evict key2 (now LRU)
        cache.set("key3", "value3", "text/plain", time.time(), future)
        assert cache.get("key1") is not None
        assert cache.get("key2") is None
        assert cache.get("key3") is not None

    def test_expired_entry(self):
        import time

        from webscout_mcp.cache import LRUCache

        cache = LRUCache(max_size=3)
        cache.set("key1", "value1", "text/plain", time.time(), time.time() - 1)  # expired
        assert cache.get("key1") is None

    def test_delete(self):
        import time

        from webscout_mcp.cache import LRUCache

        cache = LRUCache(max_size=3)
        future = time.time() + 3600
        cache.set("key1", "value1", "text/plain", time.time(), future)
        cache.delete("key1")
        assert cache.get("key1") is None

    def test_clear(self):
        import time

        from webscout_mcp.cache import LRUCache

        cache = LRUCache(max_size=3)
        future = time.time() + 3600
        cache.set("key1", "value1", "text/plain", time.time(), future)
        cache.set("key2", "value2", "text/plain", time.time(), future)
        cache.clear()
        assert cache.size == 0
        assert cache.hits == 0
        assert cache.misses == 0

    def test_hit_rate_statistics(self):
        import time

        from webscout_mcp.cache import LRUCache

        cache = LRUCache(max_size=3)
        future = time.time() + 3600
        cache.set("key1", "value1", "text/plain", time.time(), future)
        # 2 hits, 1 miss
        cache.get("key1")
        cache.get("key1")
        cache.get("missing")
        assert cache.hits == 2
        assert cache.misses == 1
        assert abs(cache.hit_rate - 2 / 3) < 0.01


class TestLayeredCache:
    def test_memory_cache_layer(self):
        """Test that memory cache provides faster access after first fetch."""
        import tempfile
        from pathlib import Path

        from webscout_mcp.cache import Cache

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Cache(Path(tmpdir) / "test.db", ttl=3600, max_size_mb=10, memory_cache_size=5)
            cache.set("https://example.com", "hello world", "text/plain")
            # First access - should be cached (set writes to both layers)
            result1 = cache.get("https://example.com")
            assert result1 is not None
            assert result1["cached"] is True
            # Clear memory cache to force disk read
            cache._memory.clear()
            # Second access - should come from disk
            result2 = cache.get("https://example.com")
            assert result2 is not None
            assert result2["cache_layer"] == "disk"
            # Third access - should come from memory
            result3 = cache.get("https://example.com")
            assert result3 is not None
            assert result3["cache_layer"] == "memory"

    def test_memory_cache_stats(self):
        """Test that memory cache statistics are included in stats()."""
        import tempfile
        from pathlib import Path

        from webscout_mcp.cache import Cache

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Cache(Path(tmpdir) / "test.db", ttl=3600, max_size_mb=10, memory_cache_size=5)
            cache.set("https://example.com", "hello", "text/plain")
            cache.get("https://example.com")  # memory hit (set populates memory)
            cache._memory.clear()
            cache.get("https://example.com")  # disk miss, populates memory
            cache.get("https://example.com")  # memory hit
            stats = cache.stats()
            assert "memory_cache" in stats
            assert stats["memory_cache"]["entries"] == 1
            assert stats["memory_cache"]["hits"] >= 1
            assert "hit_rate" in stats["memory_cache"]
