"""
Tests for utils module - utility functions.

Tests URL normalization, validation, text truncation, URL safety,
domain extraction, and TokenBucket basics.
"""

import pytest
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webscout_mcp.utils import (
    TokenBucket,
    normalize_url,
    is_valid_url,
    truncate_text,
    is_safe_url,
    extract_domain,
)


class TestTokenBucket:
    """Tests for TokenBucket rate limiter."""

    def test_initialization(self):
        """Test TokenBucket initialization."""
        bucket = TokenBucket(rate=2.0, burst=5)
        assert bucket.rate == 2.0
        assert bucket.burst == 5

    def test_default_initialization(self):
        """Test TokenBucket with default values."""
        bucket = TokenBucket()
        assert bucket.rate == 2.0
        assert bucket.burst == 5

    def test_domain_extraction(self):
        """Test _domain static method."""
        assert TokenBucket._domain("https://example.com/path") == "example.com"
        assert TokenBucket._domain("http://sub.example.com:8080") == "sub.example.com:8080"
        assert TokenBucket._domain("https://WWW.Example.COM") == "www.example.com"

    def test_domain_extraction_invalid_url(self):
        """Test _domain with invalid URL returns empty string."""
        result = TokenBucket._domain("not a url")
        assert result == ""  # Invalid URL returns empty netloc

    @pytest.mark.asyncio
    async def test_acquire_basic(self):
        """Test basic async acquire."""
        bucket = TokenBucket(rate=100.0, burst=10)  # Fast rate for testing
        await bucket.acquire("https://example.com")
        # Should not raise

    @pytest.mark.asyncio
    async def test_acquire_multiple_domains(self):
        """Test acquire for multiple domains (independent buckets)."""
        bucket = TokenBucket(rate=100.0, burst=10)
        await bucket.acquire("https://example1.com")
        await bucket.acquire("https://example2.com")
        await bucket.acquire("https://example1.com")  # Same domain again
        # Should not raise


class TestNormalizeUrl:
    """Tests for normalize_url function."""

    def test_basic_url(self):
        """Test basic URL normalization."""
        result = normalize_url("https://example.com/path")
        assert result == "https://example.com/path"

    def test_url_with_trailing_slash(self):
        """Test URL with trailing slash."""
        result = normalize_url("https://example.com/path/")
        # Should preserve or remove trailing slash consistently
        assert result.startswith("https://example.com/path")

    def test_url_with_query_params(self):
        """Test URL with query parameters."""
        result = normalize_url("https://example.com/path?param=value")
        assert "param=value" in result

    def test_url_with_fragment(self):
        """Test URL with fragment (should be stripped)."""
        result = normalize_url("https://example.com/path#section")
        # Fragments should be stripped
        assert "#" not in result
        assert result.startswith("https://example.com/path")

    def test_url_with_uppercase(self):
        """Test URL with uppercase scheme/host."""
        result = normalize_url("HTTPS://EXAMPLE.COM/Path")
        # Scheme and host should be lowercased
        assert result.startswith("https://example.com/")

    def test_url_with_port(self):
        """Test URL with port number."""
        result = normalize_url("https://example.com:8080/path")
        assert ":8080" in result

    def test_http_url(self):
        """Test HTTP URL."""
        result = normalize_url("http://example.com/path")
        assert result.startswith("http://example.com")

    def test_default_https_port_removed(self):
        """Test that default HTTPS port (443) is removed."""
        result = normalize_url("https://example.com:443/path")
        assert ":443" not in result

    def test_default_http_port_removed(self):
        """Test that default HTTP port (80) is removed."""
        result = normalize_url("http://example.com:80/path")
        assert ":80" not in result


class TestIsValidUrl:
    """Tests for is_valid_url function."""

    def test_valid_http_url(self):
        """Test valid HTTP URL."""
        assert is_valid_url("http://example.com") is True

    def test_valid_https_url(self):
        """Test valid HTTPS URL."""
        assert is_valid_url("https://example.com") is True

    def test_valid_url_with_path(self):
        """Test valid URL with path."""
        assert is_valid_url("https://example.com/path/to/page") is True

    def test_valid_url_with_query(self):
        """Test valid URL with query parameters."""
        assert is_valid_url("https://example.com/path?param=value") is True

    def test_invalid_url_no_scheme(self):
        """Test invalid URL without scheme."""
        assert is_valid_url("example.com") is False

    def test_invalid_url_empty(self):
        """Test invalid empty URL."""
        assert is_valid_url("") is False

    def test_invalid_url_whitespace(self):
        """Test invalid URL with only whitespace."""
        assert is_valid_url("   ") is False

    def test_invalid_url_ftp(self):
        """Test FTP URL (may or may not be valid depending on implementation)."""
        result = is_valid_url("ftp://example.com")
        # Should return boolean
        assert isinstance(result, bool)


class TestTruncateText:
    """Tests for truncate_text function."""

    def test_short_text(self):
        """Test text shorter than max_chars."""
        text = "Short text"
        result = truncate_text(text, max_chars=100)
        assert result == text

    def test_long_text(self):
        """Test text longer than max_chars (may include truncation marker)."""
        text = "a" * 1000
        result = truncate_text(text, max_chars=100)
        # Result may be slightly longer due to truncation marker
        assert len(result) < len(text)
        assert result.startswith("a" * 90)  # Should start with original text

    def test_exact_length(self):
        """Test text exactly max_chars length."""
        text = "a" * 100
        result = truncate_text(text, max_chars=100)
        # Should be same or slightly longer with marker
        assert len(result) >= 100

    def test_empty_text(self):
        """Test empty text."""
        result = truncate_text("", max_chars=100)
        assert result == ""

    def test_default_max_chars(self):
        """Test default max_chars (8000)."""
        text = "a" * 10000
        result = truncate_text(text)
        # Result should be significantly shorter than original
        assert len(result) < 10000

    def test_truncation_preserves_beginning(self):
        """Test that truncated text preserves the beginning."""
        text = "Important content at the beginning" + "a" * 1000
        result = truncate_text(text, max_chars=50)
        assert "Important content" in result


class TestIsSafeUrl:
    """Tests for is_safe_url function."""

    def test_safe_public_url(self):
        """Test safe public URL."""
        safe, reason = is_safe_url("https://example.com")
        assert safe is True
        assert isinstance(reason, str)

    def test_localhost_url(self):
        """Test localhost URL (should be unsafe by default)."""
        safe, reason = is_safe_url("http://localhost")
        assert safe is False
        assert "localhost" in reason.lower() or "local" in reason.lower()

    def test_private_ip_url(self):
        """Test private IP URL (should be unsafe by default)."""
        safe, reason = is_safe_url("http://192.168.1.1")
        assert safe is False
        assert "private" in reason.lower() or "192.168" in reason

    def test_loopback_ip_url(self):
        """Test loopback IP URL."""
        safe, reason = is_safe_url("http://127.0.0.1")
        assert safe is False

    def test_allow_private_localhost(self):
        """Test allowing private URLs with allow_private=True."""
        safe, reason = is_safe_url("http://localhost", allow_private=True)
        # Should be safe when allow_private is True
        assert safe is True

    def test_allow_private_ip(self):
        """Test allowing private IPs with allow_private=True."""
        safe, reason = is_safe_url("http://192.168.1.1", allow_private=True)
        assert safe is True

    def test_file_protocol_url(self):
        """Test file:// protocol URL (should be unsafe)."""
        safe, reason = is_safe_url("file:///etc/passwd")
        assert safe is False

    def test_ftp_protocol_url(self):
        """Test ftp:// protocol URL (may be unsafe)."""
        safe, reason = is_safe_url("ftp://example.com")
        # Should return boolean
        assert isinstance(safe, bool)


class TestExtractDomain:
    """Tests for extract_domain function."""

    def test_basic_domain(self):
        """Test extracting domain from basic URL."""
        result = extract_domain("https://example.com/path")
        assert result == "example.com"

    def test_domain_with_www(self):
        """Test extracting domain with www prefix."""
        result = extract_domain("https://www.example.com/path")
        assert "example.com" in result

    def test_domain_with_subdomain(self):
        """Test extracting domain with subdomain."""
        result = extract_domain("https://sub.example.com/path")
        assert "example.com" in result or result == "sub.example.com"

    def test_domain_with_port(self):
        """Test extracting domain with port."""
        result = extract_domain("https://example.com:8080/path")
        assert result == "example.com"

    def test_http_url(self):
        """Test extracting domain from HTTP URL."""
        result = extract_domain("http://example.com")
        assert result == "example.com"

    def test_url_with_query_params(self):
        """Test extracting domain from URL with query params."""
        result = extract_domain("https://example.com/path?param=value")
        assert result == "example.com"

    def test_url_with_fragment(self):
        """Test extracting domain from URL with fragment."""
        result = extract_domain("https://example.com/path#section")
        assert result == "example.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
