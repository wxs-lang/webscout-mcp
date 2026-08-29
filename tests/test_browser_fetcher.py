"""Tests for browser fetcher module."""

from webscout_mcp.browser_fetcher import (
    BrowserConfig,
    BrowserFetcher,
    BrowserResult,
    is_browser_available,
)


class TestBrowserConfig:
    """Test browser configuration."""

    def test_default_config(self):
        config = BrowserConfig()
        assert config.browser_type == "chromium"
        assert config.headless is True
        assert config.viewport_width == 1920
        assert config.viewport_height == 1080
        assert config.timeout == 30000
        assert config.navigation_timeout == 60000
        assert config.wait_for_network_idle is True
        assert config.block_images is False
        assert config.block_media is True
        assert config.stealth_mode is True

    def test_custom_config(self):
        config = BrowserConfig(
            browser_type="firefox",
            headless=False,
            viewport_width=1280,
            viewport_height=720,
            timeout=60000,
            block_images=True,
            stealth_mode=False,
        )
        assert config.browser_type == "firefox"
        assert config.headless is False
        assert config.viewport_width == 1280
        assert config.viewport_height == 720
        assert config.timeout == 60000
        assert config.block_images is True
        assert config.stealth_mode is False

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("WEBSCOUT_BROWSER_TYPE", "firefox")
        monkeypatch.setenv("WEBSCOUT_BROWSER_HEADLESS", "false")
        monkeypatch.setenv("WEBSCOUT_BROWSER_VIEWPORT_WIDTH", "1366")
        monkeypatch.setenv("WEBSCOUT_BROWSER_VIEWPORT_HEIGHT", "768")
        monkeypatch.setenv("WEBSCOUT_BROWSER_TIMEOUT", "45000")
        monkeypatch.setenv("WEBSCOUT_BROWSER_BLOCK_IMAGES", "true")
        monkeypatch.setenv("WEBSCOUT_BROWSER_STEALTH", "false")

        config = BrowserConfig.from_env()
        assert config.browser_type == "firefox"
        assert config.headless is False
        assert config.viewport_width == 1366
        assert config.viewport_height == 768
        assert config.timeout == 45000
        assert config.block_images is True
        assert config.stealth_mode is False

    def test_unsupported_browser_type_config(self):
        # Test that config stores unsupported browser type correctly
        # Actual browser launch will fail, but config should be stored
        config = BrowserConfig(browser_type="unsupported")
        assert config.browser_type == "unsupported"


class TestBrowserResult:
    """Test BrowserResult class."""

    def test_result_creation(self):
        result = BrowserResult(url="https://example.com")
        assert result.url == "https://example.com"
        assert result.title == ""
        assert result.content == ""
        assert result.html == ""
        assert result.status_code == 0
        assert result.error is None

    def test_result_with_data(self):
        result = BrowserResult(
            url="https://example.com",
            title="Example Page",
            content="Page content",
            html="<html>...</html>",
            status_code=200,
            screenshot_path="/tmp/screenshot.png",
            pdf_path="/tmp/page.pdf",
        )
        assert result.title == "Example Page"
        assert result.content == "Page content"
        assert result.status_code == 200
        assert result.screenshot_path == "/tmp/screenshot.png"
        assert result.pdf_path == "/tmp/page.pdf"

    def test_result_to_dict(self):
        result = BrowserResult(
            url="https://example.com",
            title="Test",
            status_code=200,
            error=None,
        )
        data = result.to_dict()
        assert data["url"] == "https://example.com"
        assert data["title"] == "Test"
        assert data["status_code"] == 200
        assert data["error"] is None


class TestBrowserFetcher:
    """Test BrowserFetcher class."""

    def test_fetcher_creation(self):
        config = BrowserConfig()
        fetcher = BrowserFetcher(config=config)
        assert fetcher.config == config

    def test_is_available(self):
        # Just verify it doesn't raise
        result = is_browser_available()
        assert isinstance(result, bool)

    def test_fetcher_with_default_config(self):
        fetcher = BrowserFetcher()
        assert fetcher.config.browser_type == "chromium"
        assert fetcher.config.headless is True

    def test_unsupported_browser_type_in_fetcher_config(self):
        # Test that fetcher stores unsupported browser type correctly
        # Actual browser launch will fail, but config should be stored
        config = BrowserConfig(browser_type="edge")
        fetcher = BrowserFetcher(config=config)
        assert fetcher.config.browser_type == "edge"

    def test_fetch_without_browser(self):
        # Test that fetch handles missing browser gracefully
        # This should not raise, but return error in result
        config = BrowserConfig()
        fetcher = BrowserFetcher(config=config)
        # We can't actually test fetch without playwright installed
        # Just verify the method exists and has correct signature
        assert hasattr(fetcher, "fetch")
        assert callable(fetcher.fetch)

    def test_click_element_method_exists(self):
        fetcher = BrowserFetcher()
        assert hasattr(fetcher, "click_element")
        assert callable(fetcher.click_element)

    def test_fill_form_method_exists(self):
        fetcher = BrowserFetcher()
        assert hasattr(fetcher, "fill_form")
        assert callable(fetcher.fill_form)

    def test_take_screenshot_method_exists(self):
        fetcher = BrowserFetcher()
        assert hasattr(fetcher, "take_screenshot")
        assert callable(fetcher.take_screenshot)

    def test_export_pdf_method_exists(self):
        fetcher = BrowserFetcher()
        assert hasattr(fetcher, "export_pdf")
        assert callable(fetcher.export_pdf)

    def test_get_cookies_method_exists(self):
        fetcher = BrowserFetcher()
        assert hasattr(fetcher, "get_cookies")
        assert callable(fetcher.get_cookies)

    def test_clear_cookies_method_exists(self):
        fetcher = BrowserFetcher()
        assert hasattr(fetcher, "clear_cookies")
        assert callable(fetcher.clear_cookies)

    def test_close_method_exists(self):
        fetcher = BrowserFetcher()
        assert hasattr(fetcher, "close")
        assert callable(fetcher.close)

    def test_context_manager(self):
        # Test that BrowserFetcher can be used as context manager
        fetcher = BrowserFetcher()
        assert hasattr(fetcher, "__enter__")
        assert hasattr(fetcher, "__exit__")


class TestUtilityFunctions:
    """Test utility functions."""

    def test_is_browser_available(self):
        result = is_browser_available()
        assert isinstance(result, bool)
