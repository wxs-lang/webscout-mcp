"""
Tests for cache module - LRUCache and layered Cache.

Tests cache operations, TTL, eviction, statistics, and persistence.
"""

import pytest
import sys
import os
import time
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webscout_mcp.cache import LRUCache, Cache


class TestLRUCache:
    """Tests for LRUCache."""

    def test_initialization(self):
        """Test LRUCache initialization."""
        cache = LRUCache(max_size=10)
        assert cache.max_size == 10
        assert cache.size == 0
        assert cache.hits == 0
        assert cache.misses == 0
        assert cache.hit_rate == 0.0

    def test_set_and_get(self):
        """Test basic set and get operations."""
        cache = LRUCache(max_size=10)
        now = time.time()
        cache.set("key1", "value1", "text/plain", now, now + 3600)

        result = cache.get("key1")
        assert result is not None
        assert result[0] == "value1"
        assert result[1] == "text/plain"
        assert result[2] == now
        assert result[3] == now + 3600

    def test_get_missing_key(self):
        """Test getting a missing key returns None."""
        cache = LRUCache(max_size=10)
        result = cache.get("nonexistent")
        assert result is None
        assert cache.misses == 1

    def test_get_expired_entry(self):
        """Test getting an expired entry returns None."""
        cache = LRUCache(max_size=10)
        now = time.time()
        # Set an entry that expired 10 seconds ago
        cache.set("expired", "value", "text/plain", now - 100, now - 10)

        result = cache.get("expired")
        assert result is None
        assert cache.misses == 1
        # Entry should be removed after expired access
        assert cache.size == 0

    def test_get_valid_entry(self):
        """Test getting a valid entry increments hits."""
        cache = LRUCache(max_size=10)
        now = time.time()
        cache.set("key1", "value1", "text/plain", now, now + 3600)

        result = cache.get("key1")
        assert result is not None
        assert cache.hits == 1
        assert cache.misses == 0

    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        cache = LRUCache(max_size=10)
        now = time.time()

        # 3 hits, 1 miss = 75% hit rate
        cache.set("key1", "value1", "text/plain", now, now + 3600)
        cache.get("key1")  # hit
        cache.get("key1")  # hit
        cache.get("key1")  # hit
        cache.get("missing")  # miss

        assert cache.hits == 3
        assert cache.misses == 1
        assert cache.hit_rate == 0.75

    def test_hit_rate_no_requests(self):
        """Test hit rate with no requests."""
        cache = LRUCache(max_size=10)
        assert cache.hit_rate == 0.0

    def test_delete_entry(self):
        """Test deleting an entry."""
        cache = LRUCache(max_size=10)
        now = time.time()
        cache.set("key1", "value1", "text/plain", now, now + 3600)
        assert cache.size == 1

        cache.delete("key1")
        assert cache.size == 0
        assert cache.get("key1") is None

    def test_delete_nonexistent_entry(self):
        """Test deleting a nonexistent entry doesn't raise."""
        cache = LRUCache(max_size=10)
        cache.delete("nonexistent")  # Should not raise
        assert cache.size == 0

    def test_clear_cache(self):
        """Test clearing the cache."""
        cache = LRUCache(max_size=10)
        now = time.time()
        cache.set("key1", "value1", "text/plain", now, now + 3600)
        cache.set("key2", "value2", "text/plain", now, now + 3600)
        cache.get("key1")  # hit

        cache.clear()
        assert cache.size == 0
        assert cache.hits == 0
        assert cache.misses == 0

    def test_lru_eviction(self):
        """Test LRU eviction when cache exceeds max_size."""
        cache = LRUCache(max_size=3)
        now = time.time()

        cache.set("key1", "value1", "text/plain", now, now + 3600)
        cache.set("key2", "value2", "text/plain", now, now + 3600)
        cache.set("key3", "value3", "text/plain", now, now + 3600)
        assert cache.size == 3

        # Access key1 to make it recently used
        cache.get("key1")

        # Add key4 - should evict key2 (least recently used)
        cache.set("key4", "value4", "text/plain", now, now + 3600)
        assert cache.size == 3
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key1") is not None  # Still there
        assert cache.get("key3") is not None  # Still there
        assert cache.get("key4") is not None  # Newly added

    def test_update_existing_key(self):
        """Test updating an existing key moves it to end."""
        cache = LRUCache(max_size=3)
        now = time.time()

        cache.set("key1", "value1", "text/plain", now, now + 3600)
        cache.set("key2", "value2", "text/plain", now, now + 3600)
        cache.set("key3", "value3", "text/plain", now, now + 3600)

        # Update key1 - should move to end (most recently used)
        cache.set("key1", "updated", "text/plain", now, now + 3600)

        # Add key4 - should evict key2 (least recently used)
        cache.set("key4", "value4", "text/plain", now, now + 3600)
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key1") is not None  # Still there (was updated)

    def test_max_size_one(self):
        """Test cache with max_size=1."""
        cache = LRUCache(max_size=1)
        now = time.time()

        cache.set("key1", "value1", "text/plain", now, now + 3600)
        assert cache.size == 1

        cache.set("key2", "value2", "text/plain", now, now + 3600)
        assert cache.size == 1
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") is not None

    def test_size_property(self):
        """Test size property reflects current entries."""
        cache = LRUCache(max_size=10)
        now = time.time()

        assert cache.size == 0
        cache.set("key1", "value1", "text/plain", now, now + 3600)
        assert cache.size == 1
        cache.set("key2", "value2", "text/plain", now, now + 3600)
        assert cache.size == 2
        cache.delete("key1")
        assert cache.size == 1


class TestCache:
    """Tests for layered Cache (LRU + SQLite)."""

    @pytest.fixture
    def temp_cache(self):
        """Create a temporary cache for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_cache.db"
            cache = Cache(db_path=db_path, ttl=3600, max_size_mb=10, memory_cache_size=5)
            yield cache

    def test_initialization(self, temp_cache):
        """Test Cache initialization."""
        assert temp_cache.db_path is not None
        assert temp_cache.ttl == 3600
        assert temp_cache.max_size_bytes == 10 * 1024 * 1024
        assert temp_cache._memory is not None

    def test_make_key(self):
        """Test key generation (SHA-256 hash)."""
        key1 = Cache._make_key("https://example.com")
        key2 = Cache._make_key("https://example.com")
        key3 = Cache._make_key("https://other.com")

        assert isinstance(key1, str)
        assert len(key1) == 64  # SHA-256 hex digest length
        assert key1 == key2  # Same URL = same key
        assert key1 != key3  # Different URL = different key

    def test_set_and_get(self, temp_cache):
        """Test basic set and get operations."""
        url = "https://example.com"
        content = "<html>Example</html>"
        content_type = "text/html"

        temp_cache.set(url, content, content_type)
        result = temp_cache.get(url)

        assert result is not None
        assert result["value"] == content
        assert result["content_type"] == content_type

    def test_get_missing_url(self, temp_cache):
        """Test getting a missing URL returns None."""
        result = temp_cache.get("https://nonexistent.com")
        assert result is None

    def test_get_expired_entry(self, temp_cache):
        """Test getting an expired entry returns None."""
        url = "https://example.com"
        content = "Expired content"
        content_type = "text/plain"

        # Set with very short TTL
        temp_cache.ttl = 0  # Expire immediately
        temp_cache.set(url, content, content_type)
        time.sleep(0.1)  # Wait for expiration

        result = temp_cache.get(url)
        assert result is None

    def test_delete_entry(self, temp_cache):
        """Test deleting an entry."""
        url = "https://example.com"
        temp_cache.set(url, "content", "text/plain")
        assert temp_cache.get(url) is not None

        temp_cache.delete(url)
        assert temp_cache.get(url) is None

    def test_clear_cache(self, temp_cache):
        """Test clearing the cache."""
        temp_cache.set("https://example1.com", "content1", "text/plain")
        temp_cache.set("https://example2.com", "content2", "text/plain")

        temp_cache.clear()
        assert temp_cache.get("https://example1.com") is None
        assert temp_cache.get("https://example2.com") is None

    def test_cache_persistence(self):
        """Test cache persistence across instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "persistent.db"

            # First instance - set a value
            cache1 = Cache(db_path=db_path, ttl=3600)
            cache1.set("https://example.com", "persistent content", "text/plain")

            # Second instance - should be able to get the value
            cache2 = Cache(db_path=db_path, ttl=3600)
            result = cache2.get("https://example.com")
            assert result is not None
            assert result["value"] == "persistent content"

    def test_memory_cache_hit(self, temp_cache):
        """Test that memory cache is used for repeated access."""
        url = "https://example.com"
        temp_cache.set(url, "content", "text/plain")

        # First access - may come from DB or memory
        result1 = temp_cache.get(url)
        assert result1 is not None

        # Second access - should come from memory cache
        result2 = temp_cache.get(url)
        assert result2 is not None
        assert result2["value"] == "content"

    def test_multiple_urls(self, temp_cache):
        """Test caching multiple URLs."""
        urls = [
            "https://example1.com",
            "https://example2.com",
            "https://example3.com",
        ]

        for i, url in enumerate(urls):
            temp_cache.set(url, f"content{i}", "text/plain")

        for i, url in enumerate(urls):
            result = temp_cache.get(url)
            assert result is not None
            assert result["value"] == f"content{i}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
