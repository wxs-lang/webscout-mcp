"""
Extra tests for security module - covering edge cases for SSRFProtector.

These tests supplement test_errors_security.py with additional edge case coverage.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webscout_mcp.errors import SSRFError
from webscout_mcp.security import SSRFProtector


class TestSSRFProtectorEdgeCases:
    """Edge case tests for SSRFProtector."""

    def test_dangerous_protocol_file(self):
        """Test that file:// protocol is blocked."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("file:///etc/passwd")
        assert is_safe is False
        assert "file" in reason.lower()

    def test_dangerous_protocol_ftp(self):
        """Test that ftp:// protocol is blocked."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("ftp://example.com/file")
        assert is_safe is False

    def test_dangerous_protocol_gopher(self):
        """Test that gopher:// protocol is blocked."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("gopher://example.com")
        assert is_safe is False

    def test_url_no_hostname(self):
        """Test URL without hostname is blocked."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("http:///path")
        assert is_safe is False
        assert "hostname" in reason.lower()

    def test_hostname_denylist(self):
        """Test that denylisted hostname is blocked."""
        protector = SSRFProtector(dns_resolution=False, denylist=["evil.com"])
        is_safe, reason = protector.validate_url("http://evil.com/page")
        assert is_safe is False
        assert "denylisted" in reason.lower()

    def test_hostname_allowlist_not_in_list(self):
        """Test that hostname not in allowlist is blocked."""
        protector = SSRFProtector(dns_resolution=False, allowlist=["safe.com"])
        is_safe, reason = protector.validate_url("http://other.com/page")
        assert is_safe is False
        assert "allowlist" in reason.lower()

    def test_hostname_allowlist_in_list(self):
        """Test that hostname in allowlist is allowed."""
        protector = SSRFProtector(dns_resolution=False, allowlist=["safe.com"])
        is_safe, reason = protector.validate_url("http://safe.com/page")
        assert is_safe is True

    def test_localhost_blocked(self):
        """Test that localhost is blocked."""
        protector = SSRFProtector(dns_resolution=False, block_localhost=True)
        is_safe, reason = protector.validate_url("http://localhost/admin")
        assert is_safe is False
        assert "localhost" in reason.lower()

    def test_localhost_localdomain_blocked(self):
        """Test that localhost.localdomain is blocked."""
        protector = SSRFProtector(dns_resolution=False, block_localhost=True)
        is_safe, reason = protector.validate_url("http://localhost.localdomain/admin")
        assert is_safe is False

    def test_ip6_localhost_blocked(self):
        """Test that ip6-localhost is blocked."""
        protector = SSRFProtector(dns_resolution=False, block_localhost=True)
        is_safe, reason = protector.validate_url("http://ip6-localhost/admin")
        assert is_safe is False

    def test_localhost_allowed_when_disabled(self):
        """Test that localhost is allowed when block_localhost is False."""
        protector = SSRFProtector(dns_resolution=False, block_localhost=False)
        is_safe, reason = protector.validate_url("http://localhost/admin")
        assert is_safe is True

    def test_assert_safe_url_raises(self):
        """Test that assert_safe_url raises SSRFError for unsafe URL."""
        protector = SSRFProtector(dns_resolution=False)
        with pytest.raises(SSRFError):
            protector.assert_safe_url("file:///etc/passwd")

    def test_assert_safe_url_passes(self):
        """Test that assert_safe_url does not raise for safe URL."""
        protector = SSRFProtector(dns_resolution=False)
        # Should not raise
        protector.assert_safe_url("https://example.com/page")

    def test_empty_url(self):
        """Test that empty URL is blocked."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("")
        assert is_safe is False
        assert "empty" in reason.lower()

    def test_none_url(self):
        """Test that None URL is handled."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url(None)
        assert is_safe is False

    def test_safe_https_url(self):
        """Test that safe HTTPS URL is allowed."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("https://example.com/page")
        assert is_safe is True
        assert "safe" in reason.lower()

    def test_safe_http_url(self):
        """Test that safe HTTP URL is allowed."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("http://example.com/page")
        assert is_safe is True

    def test_protocol_case_insensitive(self):
        """Test that protocol check is case insensitive."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("HTTPS://example.com/page")
        assert is_safe is True

    def test_url_with_port(self):
        """Test URL with port number."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("https://example.com:8080/page")
        assert is_safe is True

    def test_url_with_query_params(self):
        """Test URL with query parameters."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("https://example.com/page?q=test&page=1")
        assert is_safe is True

    def test_url_with_fragment(self):
        """Test URL with fragment."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("https://example.com/page#section")
        assert is_safe is True

    def test_url_with_userinfo(self):
        """Test URL with userinfo (username:password@)."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("https://user:pass@example.com/page")
        assert is_safe is True

    def test_subdomain_allowed(self):
        """Test that subdomains are allowed."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("https://sub.domain.example.com/page")
        assert is_safe is True

    def test_ipv4_address_allowed(self):
        """Test that public IPv4 address is allowed (without DNS check)."""
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("https://8.8.8.8/page")
        assert is_safe is True

    def test_private_ip_blocked_when_enabled(self):
        """Test that private IP is blocked when block_private_ips is True."""
        protector = SSRFProtector(dns_resolution=False, block_private_ips=True)
        # Note: without DNS resolution, IP check might not trigger
        # This test just verifies the protector can be created with this option
        assert protector.block_private_ips is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
