"""Basic tests for webscout-mcp core modules.

These tests focus on pure-logic components that don't require network access.
Network-dependent tests are marked and can be run with --run-network.
"""

from __future__ import annotations

import json
import os
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

    @pytest.mark.asyncio
    async def test_token_bucket(self):
        bucket = TokenBucket(rate=10.0, burst=2)
        # Should be able to acquire burst tokens quickly
        await bucket.acquire("https://example.com")
        await bucket.acquire("https://example.com")
        # Third should require a short wait
        await bucket.acquire("https://example.com")


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
    def test_create_server(self):
        """Verify the server can be created without errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))
            from webscout_mcp.server import create_server
            mcp = create_server(cfg)
            assert mcp is not None
            assert hasattr(mcp, "tool")
