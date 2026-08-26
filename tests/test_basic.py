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
        assert cfg.timeout == 15
        assert cfg.max_retries == 3
        assert cfg.user_agent_rotation is True

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_TIMEOUT", "30")
        monkeypatch.setenv("WEBSCOUT_MAX_RETRIES", "5")
        cfg = Config.from_env()
        assert cfg.timeout == 30
        assert cfg.max_retries == 5

    def test_ensure_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir) / "cache")
            cfg.ensure_dirs()
            assert (Path(tmpdir) / "cache").is_dir()


# --- Cache ---

class TestCache:
    def test_set_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Cache(cache_dir=Path(tmpdir))
            cache.set("key1", {"data": "value1"}, ttl=60)
            result = cache.get("key1")
            assert result is not None
            assert result["data"] == "value1"

    def test_get_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Cache(cache_dir=Path(tmpdir))
            assert cache.get("nonexistent") is None

    def test_expiry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Cache(cache_dir=Path(tmpdir))
            cache.set("expiring", {"data": "temp"}, ttl=0)
            import time
            time.sleep(0.1)
            assert cache.get("expiring") is None

    def test_delete(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Cache(cache_dir=Path(tmpdir))
            cache.set("todelete", {"data": "x"}, ttl=60)
            cache.delete("todelete")
            assert cache.get("todelete") is None

    def test_clear(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Cache(cache_dir=Path(tmpdir))
            cache.set("a", {"x": 1}, ttl=60)
            cache.set("b", {"x": 2}, ttl=60)
            cache.clear()
            assert cache.get("a") is None
            assert cache.get("b") is None

    def test_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = Cache(cache_dir=Path(tmpdir))
            cache.set("s1", {"x": 1}, ttl=60)
            stats = cache.stats()
            assert stats["total_entries"] >= 1


# --- Utils ---

class TestUtils:
    def test_normalize_url(self):
        assert normalize_url("HTTP://Example.COM/Path") == "http://example.com/Path"

    def test_normalize_url_strips_fragment(self):
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_is_valid_url(self):
        assert is_valid_url("https://example.com") is True
        assert is_valid_url("not-a-url") is False
        assert is_valid_url("") is False

    def test_truncate_text(self):
        long_text = "a" * 2000
        result = truncate_text(long_text, max_length=1000)
        assert len(result) <= 1000
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
        <div class="content">
            <p>First paragraph.</p>
            <p>Second paragraph.</p>
        </div>
        <a href="https://example.com/link1">Link 1</a>
        <a href="https://example.com/link2">Link 2</a>
        <span class="price">$29.99</span>
    </body>
    </html>
    """

    def test_extract_single_text(self):
        extractor = DataExtractor(Config(), None)
        rules = [ExtractionRule(name="title", selector="h1.title", attribute="text")]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert result["title"] == "Hello World"

    def test_extract_with_regex(self):
        extractor = DataExtractor(Config(), None)
        rules = [
            ExtractionRule(
                name="price_value",
                selector=".price",
                attribute="text",
                regex=r"\$([\d.]+)",
            )
        ]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert result["price_value"] == "29.99"

    def test_extract_attribute_multiple(self):
        extractor = DataExtractor(Config(), None)
        rules = [ExtractionRule(name="links", selector="a", attribute="href", multiple=True)]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert len(result["links"]) == 2
        assert "https://example.com/link1" in result["links"]

    def test_extract_default_on_missing(self):
        extractor = DataExtractor(Config(), None)
        rules = [ExtractionRule(name="missing", selector=".nonexistent", default="N/A")]
        result = extractor.extract_from_html(self.SAMPLE_HTML, rules)
        assert result["missing"] == "N/A"


# --- MCP Server (import test) ---

class TestServer:
    def test_create_server(self):
        """Verify the server can be created without errors."""
        pytest.importorskip("mcp")
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Config(cache_dir=Path(tmpdir))
            from webscout_mcp.server import create_server
            server = create_server(cfg)
            assert server is not None
