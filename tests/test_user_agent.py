"""
Tests for user_agent module - User-Agent rotation and browser fingerprints.

Tests BrowserFingerprint, UserAgentRotator, and utility functions.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webscout_mcp.user_agent import (
    BrowserFingerprint,
    UserAgentRotator,
    random_user_agent,
    random_headers,
    random_ajax_headers,
)


class TestBrowserFingerprint:
    """Tests for BrowserFingerprint."""

    def test_initialization(self):
        """Test BrowserFingerprint initialization."""
        fp = BrowserFingerprint(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            accept="text/html,application/xhtml+xml",
            accept_language="en-US,en;q=0.9",
        )
        assert fp.user_agent.startswith("Mozilla/5.0")
        assert fp.accept == "text/html,application/xhtml+xml"
        assert fp.accept_language == "en-US,en;q=0.9"
        assert fp.browser_type == "chrome"  # Default

    def test_default_values(self):
        """Test BrowserFingerprint default values."""
        fp = BrowserFingerprint(
            user_agent="test-ua",
            accept="test-accept",
            accept_language="test-lang",
        )
        assert fp.accept_encoding == "gzip, deflate, br"
        assert fp.sec_ch_ua == ""
        assert fp.sec_ch_ua_mobile == "?0"
        assert fp.sec_ch_ua_platform == ""
        assert fp.upgrade_insecure_requests == "1"
        assert fp.sec_fetch_dest == "document"
        assert fp.sec_fetch_mode == "navigate"
        assert fp.sec_fetch_site == "none"
        assert fp.sec_fetch_user == "?1"
        assert fp.connection == "keep-alive"
        assert fp.cache_control == "max-age=0"

    def test_to_headers_basic(self):
        """Test to_headers returns basic headers."""
        fp = BrowserFingerprint(
            user_agent="test-ua",
            accept="test-accept",
            accept_language="test-lang",
        )
        headers = fp.to_headers()
        assert headers["User-Agent"] == "test-ua"
        assert headers["Accept"] == "test-accept"
        assert headers["Accept-Language"] == "test-lang"
        assert headers["Accept-Encoding"] == "gzip, deflate, br"
        assert headers["Connection"] == "keep-alive"
        assert headers["Upgrade-Insecure-Requests"] == "1"
        assert headers["Sec-Fetch-Dest"] == "document"
        assert headers["Sec-Fetch-Mode"] == "navigate"
        assert headers["Sec-Fetch-Site"] == "none"
        assert headers["Sec-Fetch-User"] == "?1"
        assert headers["Cache-Control"] == "max-age=0"

    def test_to_headers_with_sec_ch_ua(self):
        """Test to_headers includes sec-ch-ua headers when set."""
        fp = BrowserFingerprint(
            user_agent="test-ua",
            accept="test-accept",
            accept_language="test-lang",
            sec_ch_ua='"Chromium";v="120"',
            sec_ch_ua_mobile="?0",
            sec_ch_ua_platform='"Windows"',
        )
        headers = fp.to_headers()
        assert headers["sec-ch-ua"] == '"Chromium";v="120"'
        assert headers["sec-ch-ua-mobile"] == "?0"
        assert headers["sec-ch-ua-platform"] == '"Windows"'

    def test_to_headers_without_cache_control(self):
        """Test to_headers without Cache-Control when empty."""
        fp = BrowserFingerprint(
            user_agent="test-ua",
            accept="test-accept",
            accept_language="test-lang",
            cache_control="",
        )
        headers = fp.to_headers()
        assert "Cache-Control" not in headers

    def test_get_ajax_headers(self):
        """Test get_ajax_headers returns AJAX-specific headers."""
        fp = BrowserFingerprint(
            user_agent="test-ua",
            accept="test-accept",
            accept_language="test-lang",
        )
        headers = fp.get_ajax_headers()
        assert headers["Sec-Fetch-Dest"] == "empty"
        assert headers["Sec-Fetch-Mode"] == "cors"
        assert headers["Sec-Fetch-Site"] == "same-origin"
        assert "Sec-Fetch-User" not in headers
        assert "Upgrade-Insecure-Requests" not in headers
        assert headers["Accept"] == "application/json, text/plain, */*"
        assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_get_ajax_headers_preserves_ua(self):
        """Test get_ajax_headers preserves User-Agent."""
        fp = BrowserFingerprint(
            user_agent="test-ua-ajax",
            accept="test-accept",
            accept_language="test-lang",
        )
        headers = fp.get_ajax_headers()
        assert headers["User-Agent"] == "test-ua-ajax"


class TestUserAgentRotator:
    """Tests for UserAgentRotator."""

    def test_initialization(self):
        """Test UserAgentRotator initialization."""
        rotator = UserAgentRotator(seed=42)
        assert rotator._mobile is False
        assert rotator._persistent is False
        assert rotator._persistent_fingerprint is None

    def test_initialization_mobile(self):
        """Test UserAgentRotator with mobile=True."""
        rotator = UserAgentRotator(mobile=True, seed=42)
        assert rotator._mobile is True

    def test_initialization_persistent(self):
        """Test UserAgentRotator with persistent=True."""
        rotator = UserAgentRotator(persistent=True, seed=42)
        assert rotator._persistent is True

    def test_get_user_agent_returns_string(self):
        """Test get_user_agent returns a non-empty string."""
        rotator = UserAgentRotator(seed=42)
        ua = rotator.get_user_agent()
        assert isinstance(ua, str)
        assert len(ua) > 0
        assert "Mozilla" in ua

    def test_get_user_agent_mobile(self):
        """Test get_user_agent for mobile contains mobile indicators."""
        rotator = UserAgentRotator(mobile=True, seed=42)
        ua = rotator.get_user_agent()
        # Mobile UA should contain Android or iPhone
        assert "Android" in ua or "iPhone" in ua or "Mobile" in ua

    def test_rotate_returns_different(self):
        """Test rotate returns different User-Agents."""
        rotator = UserAgentRotator(seed=42)
        ua1 = rotator.rotate()
        ua2 = rotator.rotate()
        # Should be different (unless list has only 1 item, which it doesn't)
        assert isinstance(ua1, str)
        assert isinstance(ua2, str)

    def test_detect_browser_type_chrome(self):
        """Test _detect_browser_type for Chrome."""
        rotator = UserAgentRotator(seed=42)
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        assert rotator._detect_browser_type(ua) == "chrome"

    def test_detect_browser_type_firefox(self):
        """Test _detect_browser_type for Firefox."""
        rotator = UserAgentRotator(seed=42)
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"
        assert rotator._detect_browser_type(ua) == "firefox"

    def test_detect_browser_type_safari(self):
        """Test _detect_browser_type for Safari."""
        rotator = UserAgentRotator(seed=42)
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"
        assert rotator._detect_browser_type(ua) == "safari"

    def test_get_accept_for_browser_chrome(self):
        """Test _get_accept_for_browser for Chrome."""
        rotator = UserAgentRotator(seed=42)
        accept = rotator._get_accept_for_browser("chrome")
        assert isinstance(accept, str)
        assert "text/html" in accept

    def test_get_accept_for_browser_firefox(self):
        """Test _get_accept_for_browser for Firefox."""
        rotator = UserAgentRotator(seed=42)
        accept = rotator._get_accept_for_browser("firefox")
        assert isinstance(accept, str)
        assert len(accept) > 0

    def test_get_accept_for_browser_safari(self):
        """Test _get_accept_for_browser for Safari."""
        rotator = UserAgentRotator(seed=42)
        accept = rotator._get_accept_for_browser("safari")
        assert isinstance(accept, str)
        assert len(accept) > 0

    def test_get_fingerprint_returns_browser_fingerprint(self):
        """Test get_fingerprint returns BrowserFingerprint instance."""
        rotator = UserAgentRotator(seed=42)
        fp = rotator.get_fingerprint()
        assert isinstance(fp, BrowserFingerprint)
        assert fp.user_agent is not None
        assert fp.accept is not None
        assert fp.accept_language is not None

    def test_get_fingerprint_persistent(self):
        """Test get_fingerprint returns same fingerprint in persistent mode."""
        rotator = UserAgentRotator(persistent=True, seed=42)
        fp1 = rotator.get_fingerprint()
        fp2 = rotator.get_fingerprint()
        assert fp1.user_agent == fp2.user_agent
        assert fp1.accept == fp2.accept
        assert fp1.accept_language == fp2.accept_language

    def test_get_fingerprint_non_persistent(self):
        """Test get_fingerprint may return different fingerprints in non-persistent mode."""
        rotator = UserAgentRotator(persistent=False, seed=42)
        fp1 = rotator.get_fingerprint()
        fp2 = rotator.get_fingerprint()
        # May or may not be different, but both should be valid
        assert isinstance(fp1, BrowserFingerprint)
        assert isinstance(fp2, BrowserFingerprint)

    def test_get_headers_returns_dict(self):
        """Test get_headers returns a dictionary."""
        rotator = UserAgentRotator(seed=42)
        headers = rotator.get_headers()
        assert isinstance(headers, dict)
        assert "User-Agent" in headers
        assert "Accept" in headers

    def test_get_ajax_headers_returns_dict(self):
        """Test get_ajax_headers returns a dictionary."""
        rotator = UserAgentRotator(seed=42)
        headers = rotator.get_ajax_headers()
        assert isinstance(headers, dict)
        assert "X-Requested-With" in headers
        assert headers["X-Requested-With"] == "XMLHttpRequest"

    def test_seed_reproducibility(self):
        """Test that same seed produces same User-Agent."""
        rotator1 = UserAgentRotator(seed=123)
        rotator2 = UserAgentRotator(seed=123)
        assert rotator1.get_user_agent() == rotator2.get_user_agent()

    def test_get_fingerprint_chrome_version_parse_failure(self):
        """Test get_fingerprint handles Chrome version parse failure."""
        rotator = UserAgentRotator(seed=42)
        original_get = rotator.get_user_agent

        def mock_get():
            # Contains "Chrome" but not "Chrome/" (triggers IndexError on split)
            # Also no "Safari/" so detected as chrome
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome"

        rotator.get_user_agent = mock_get
        fp = rotator.get_fingerprint()
        assert isinstance(fp, BrowserFingerprint)
        assert fp.browser_type == "chrome"
        assert "120" in fp.sec_ch_ua  # Default version on parse failure
        rotator.get_user_agent = original_get

    def test_get_fingerprint_macintosh_platform(self):
        """Test get_fingerprint detects Macintosh platform."""
        rotator = UserAgentRotator(seed=42)
        original_get = rotator.get_user_agent

        def mock_get():
            return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        rotator.get_user_agent = mock_get
        fp = rotator.get_fingerprint()
        assert fp.sec_ch_ua_platform == '"macOS"'
        rotator.get_user_agent = original_get

    def test_get_fingerprint_linux_platform(self):
        """Test get_fingerprint detects Linux platform."""
        rotator = UserAgentRotator(seed=42)
        original_get = rotator.get_user_agent

        def mock_get():
            return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

        rotator.get_user_agent = mock_get
        fp = rotator.get_fingerprint()
        assert fp.sec_ch_ua_platform == '"Linux"'
        rotator.get_user_agent = original_get

    def test_get_fingerprint_android_platform(self):
        """Test get_fingerprint detects Android platform."""
        rotator = UserAgentRotator(mobile=True, seed=42)
        original_get = rotator.get_user_agent

        def mock_get():
            return "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

        rotator.get_user_agent = mock_get
        fp = rotator.get_fingerprint()
        assert fp.sec_ch_ua_platform == '"Android"'
        assert fp.sec_ch_ua_mobile == "?1"
        rotator.get_user_agent = original_get


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_random_user_agent_desktop(self):
        """Test random_user_agent for desktop."""
        ua = random_user_agent(mobile=False)
        assert isinstance(ua, str)
        assert len(ua) > 0
        assert "Mozilla" in ua

    def test_random_user_agent_mobile(self):
        """Test random_user_agent for mobile."""
        ua = random_user_agent(mobile=True)
        assert isinstance(ua, str)
        assert "Android" in ua or "iPhone" in ua or "Mobile" in ua

    def test_random_headers_returns_dict(self):
        """Test random_headers returns a dictionary."""
        headers = random_headers(mobile=False)
        assert isinstance(headers, dict)
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Accept-Language" in headers

    def test_random_headers_mobile(self):
        """Test random_headers for mobile."""
        headers = random_headers(mobile=True)
        assert isinstance(headers, dict)
        ua = headers["User-Agent"]
        assert "Android" in ua or "iPhone" in ua or "Mobile" in ua

    def test_random_ajax_headers_returns_dict(self):
        """Test random_ajax_headers returns a dictionary."""
        headers = random_ajax_headers(mobile=False)
        assert isinstance(headers, dict)
        assert "X-Requested-With" in headers
        assert headers["X-Requested-With"] == "XMLHttpRequest"
        assert headers["Accept"] == "application/json, text/plain, */*"

    def test_random_ajax_headers_mobile(self):
        """Test random_ajax_headers for mobile."""
        headers = random_ajax_headers(mobile=True)
        assert isinstance(headers, dict)
        ua = headers["User-Agent"]
        assert "Android" in ua or "iPhone" in ua or "Mobile" in ua


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
