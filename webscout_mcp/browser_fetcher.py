"""Headless browser fetcher for webscout-mcp.
Provides browser automation capabilities using Playwright.

Features:
- JavaScript-rendered page fetching
- Simulate user interactions (scroll, click, fill forms)
- Screenshot capture
- PDF export
- Login state management (cookie persistence)
- Wait for elements/network idle
- Anti-detection measures
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Optional, Any
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class BrowserConfig:
    """Configuration for browser fetcher."""
    # Browser type: chromium, firefox, webkit
    browser_type: str = "chromium"
    # Whether to run in headless mode
    headless: bool = True
    # Viewport size
    viewport_width: int = 1920
    viewport_height: int = 1080
    # User agent
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    # Timeout in milliseconds
    timeout: int = 30000
    # Navigation timeout in milliseconds
    navigation_timeout: int = 60000
    # Whether to wait for network idle
    wait_for_network_idle: bool = True
    # Network idle timeout in milliseconds
    network_idle_timeout: int = 5000
    # Whether to block images (faster loading)
    block_images: bool = False
    # Whether to block media (video/audio)
    block_media: bool = True
    # Whether to block CSS (faster loading)
    block_css: bool = False
    # Whether to block fonts
    block_fonts: bool = False
    # Cookie storage path
    cookie_storage_path: str = "~/.cache/webscout/cookies.json"
    # Whether to stealth mode (anti-detection)
    stealth_mode: bool = True
    # Slow motion in milliseconds (for debugging)
    slow_mo: int = 0
    # Proxy settings
    proxy_server: str = ""
    proxy_username: str = ""
    proxy_password: str = ""

    @classmethod
    def from_env(cls) -> "BrowserConfig":
        """Load configuration from environment variables."""
        import os
        return cls(
            browser_type=os.environ.get("WEBSCOUT_BROWSER_TYPE", "chromium"),
            headless=os.environ.get("WEBSCOUT_BROWSER_HEADLESS", "true").lower() == "true",
            viewport_width=int(os.environ.get("WEBSCOUT_BROWSER_VIEWPORT_WIDTH", "1920")),
            viewport_height=int(os.environ.get("WEBSCOUT_BROWSER_VIEWPORT_HEIGHT", "1080")),
            user_agent=os.environ.get("WEBSCOUT_BROWSER_USER_AGENT", cls.user_agent),
            timeout=int(os.environ.get("WEBSCOUT_BROWSER_TIMEOUT", "30000")),
            navigation_timeout=int(os.environ.get("WEBSCOUT_BROWSER_NAVIGATION_TIMEOUT", "60000")),
            wait_for_network_idle=os.environ.get("WEBSCOUT_BROWSER_WAIT_NETWORK_IDLE", "true").lower() == "true",
            block_images=os.environ.get("WEBSCOUT_BROWSER_BLOCK_IMAGES", "false").lower() == "true",
            block_media=os.environ.get("WEBSCOUT_BROWSER_BLOCK_MEDIA", "true").lower() == "true",
            block_css=os.environ.get("WEBSCOUT_BROWSER_BLOCK_CSS", "false").lower() == "true",
            block_fonts=os.environ.get("WEBSCOUT_BROWSER_BLOCK_FONTS", "false").lower() == "true",
            cookie_storage_path=os.environ.get("WEBSCOUT_BROWSER_COOKIE_PATH", "~/.cache/webscout/cookies.json"),
            stealth_mode=os.environ.get("WEBSCOUT_BROWSER_STEALTH", "true").lower() == "true",
            slow_mo=int(os.environ.get("WEBSCOUT_BROWSER_SLOW_MO", "0")),
            proxy_server=os.environ.get("WEBSCOUT_BROWSER_PROXY_SERVER", ""),
            proxy_username=os.environ.get("WEBSCOUT_BROWSER_PROXY_USERNAME", ""),
            proxy_password=os.environ.get("WEBSCOUT_BROWSER_PROXY_PASSWORD", ""),
        )


@dataclass
class BrowserResult:
    """Result from browser fetching."""
    url: str
    title: str = ""
    content: str = ""
    html: str = ""
    status_code: int = 0
    screenshot_path: str = ""
    pdf_path: str = ""
    cookies: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "html": self.html,
            "status_code": self.status_code,
            "screenshot_path": self.screenshot_path,
            "pdf_path": self.pdf_path,
            "cookies": self.cookies,
            "metadata": self.metadata,
            "error": self.error,
        }


class BrowserFetcher:
    """Headless browser fetcher using Playwright.

    Provides browser automation capabilities:
    - JavaScript-rendered page fetching
    - User interaction simulation
    - Screenshot and PDF capture
    - Login state management
    """

    def __init__(self, config: Optional[BrowserConfig] = None) -> None:
        self.config = config or BrowserConfig.from_env()
        self._playwright = None
        self._browser = None
        self._context = None

    def is_available(self) -> bool:
        """Check if Playwright is available."""
        try:
            import playwright
            return True
        except ImportError:
            return False

    def _get_playwright(self):
        """Get or create Playwright instance."""
        if self._playwright:
            return self._playwright

        try:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
        except ImportError:
            raise ImportError(
                "playwright is required for browser fetcher. "
                "Install with: pip install playwright && playwright install chromium"
            )

        return self._playwright

    def _get_browser(self):
        """Get or create browser instance."""
        if self._browser:
            return self._browser

        playwright = self._get_playwright()

        launch_args = {
            "headless": self.config.headless,
            "slow_mo": self.config.slow_mo,
        }

        if self.config.proxy_server:
            launch_args["proxy"] = {
                "server": self.config.proxy_server,
                "username": self.config.proxy_username or None,
                "password": self.config.proxy_password or None,
            }

        if self.config.browser_type == "chromium":
            self._browser = playwright.chromium.launch(**launch_args)
        elif self.config.browser_type == "firefox":
            self._browser = playwright.firefox.launch(**launch_args)
        elif self.config.browser_type == "webkit":
            self._browser = playwright.webkit.launch(**launch_args)
        else:
            raise ValueError(f"Unsupported browser type: {self.config.browser_type}")

        return self._browser

    def _get_context(self):
        """Get or create browser context."""
        if self._context:
            return self._context

        browser = self._get_browser()

        context_args = {
            "viewport": {
                "width": self.config.viewport_width,
                "height": self.config.viewport_height,
            },
            "user_agent": self.config.user_agent,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }

        self._context = browser.new_context(**context_args)

        # Set default timeouts
        self._context.set_default_timeout(self.config.timeout)
        self._context.set_default_navigation_timeout(self.config.navigation_timeout)

        # Load cookies if available
        self._load_cookies()

        # Apply stealth mode
        if self.config.stealth_mode:
            self._apply_stealth()

        # Block resources if configured
        if self.config.block_images or self.config.block_media or self.config.block_css or self.config.block_fonts:
            self._setup_resource_blocking()

        return self._context

    def _apply_stealth(self):
        """Apply anti-detection measures."""
        context = self._get_context()
        context.add_init_script("""
            // Override navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // Override navigator.plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // Override navigator.languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en']
            });

            // Override chrome object
            window.chrome = {
                runtime: {}
            };

            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        """)

    def _setup_resource_blocking(self):
        """Setup resource blocking for faster loading."""
        context = self._get_context()

        def handle_route(route):
            resource_type = route.request.resource_type
            if self.config.block_images and resource_type == "image":
                route.abort()
            elif self.config.block_media and resource_type in ("media", "video", "audio"):
                route.abort()
            elif self.config.block_css and resource_type == "stylesheet":
                route.abort()
            elif self.config.block_fonts and resource_type == "font":
                route.abort()
            else:
                route.continue_()

        context.route("**/*", handle_route)

    def _load_cookies(self):
        """Load cookies from storage."""
        import os
        import json
        cookie_path = os.path.expanduser(self.config.cookie_storage_path)
        if os.path.exists(cookie_path):
            try:
                with open(cookie_path, "r") as f:
                    cookies = json.load(f)
                context = self._get_context()
                context.add_cookies(cookies)
                log.info("Cookies loaded from storage", extra={"path": cookie_path, "count": len(cookies)})
            except Exception as exc:
                log.warning("Failed to load cookies", extra={"error": str(exc)})

    def _save_cookies(self):
        """Save cookies to storage."""
        import os
        import json
        context = self._get_context()
        cookies = context.cookies()
        cookie_path = os.path.expanduser(self.config.cookie_storage_path)
        os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
        with open(cookie_path, "w") as f:
            json.dump(cookies, f, indent=2)
        log.info("Cookies saved to storage", extra={"path": cookie_path, "count": len(cookies)})

    def fetch(
        self,
        url: str,
        wait_for_selector: str = "",
        scroll_to_bottom: bool = False,
        screenshot_path: str = "",
        pdf_path: str = "",
    ) -> BrowserResult:
        """Fetch a URL using headless browser.

        Args:
            url: URL to fetch.
            wait_for_selector: CSS selector to wait for.
            scroll_to_bottom: Whether to scroll to bottom of page.
            screenshot_path: Path to save screenshot.
            pdf_path: Path to save PDF.

        Returns:
            BrowserResult with page content.
        """
        result = BrowserResult(url=url)

        try:
            context = self._get_context()
            page = context.new_page()

            # Navigate to URL
            response = page.goto(url, wait_until="domcontentloaded")

            if response:
                result.status_code = response.status

            # Wait for network idle if configured
            if self.config.wait_for_network_idle:
                try:
                    page.wait_for_load_state("networkidle", timeout=self.config.network_idle_timeout)
                except Exception:
                    pass  # Network idle may not be reached, continue anyway

            # Wait for specific selector if provided
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, state="visible")

            # Scroll to bottom if configured (for lazy loading)
            if scroll_to_bottom:
                self._scroll_to_bottom(page)

            # Get page content
            result.title = page.title()
            result.html = page.content()
            result.content = page.inner_text("body")

            # Take screenshot if path provided
            if screenshot_path:
                page.screenshot(path=screenshot_path, full_page=True)
                result.screenshot_path = screenshot_path

            # Export PDF if path provided
            if pdf_path:
                page.pdf(path=pdf_path, format="A4")
                result.pdf_path = pdf_path

            # Get cookies
            result.cookies = context.cookies()

            # Save cookies
            self._save_cookies()

            # Close page
            page.close()

            log.info("Browser fetch completed", extra={
                "url": url,
                "status": result.status_code,
                "title": result.title,
                "content_length": len(result.content),
            })

        except Exception as exc:
            log.error("Browser fetch failed", extra={"url": url, "error": str(exc)})
            result.error = f"{type(exc).__name__}: {exc}"

        return result

    def _scroll_to_bottom(self, page):
        """Scroll to bottom of page to trigger lazy loading."""
        previous_height = 0
        for _ in range(10):  # Max 10 scrolls
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)  # Wait for content to load
            current_height = page.evaluate("document.body.scrollHeight")
            if current_height == previous_height:
                break  # Reached bottom
            previous_height = current_height

    def click_element(self, url: str, selector: str, wait_after: int = 2000) -> BrowserResult:
        """Navigate to URL and click an element.

        Args:
            url: URL to navigate to.
            selector: CSS selector of element to click.
            wait_after: Milliseconds to wait after click.

        Returns:
            BrowserResult with page content after click.
        """
        result = self.fetch(url)
        if result.error:
            return result

        try:
            context = self._get_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector(selector, state="visible")
            page.click(selector)
            page.wait_for_timeout(wait_after)

            result.title = page.title()
            result.html = page.content()
            result.content = page.inner_text("body")
            page.close()

        except Exception as exc:
            log.error("Click element failed", extra={"url": url, "selector": selector, "error": str(exc)})
            result.error = f"{type(exc).__name__}: {exc}"

        return result

    def fill_form(
        self,
        url: str,
        form_data: dict[str, str],
        submit_selector: str = "",
        wait_after: int = 2000,
    ) -> BrowserResult:
        """Navigate to URL and fill a form.

        Args:
            url: URL to navigate to.
            form_data: Dictionary of selector -> value for form fields.
            submit_selector: CSS selector of submit button (optional).
            wait_after: Milliseconds to wait after submit.

        Returns:
            BrowserResult with page content after form submission.
        """
        result = self.fetch(url)
        if result.error:
            return result

        try:
            context = self._get_context()
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded")

            # Fill form fields
            for selector, value in form_data.items():
                page.wait_for_selector(selector, state="visible")
                page.fill(selector, value)

            # Submit form if submit selector provided
            if submit_selector:
                page.click(submit_selector)
                page.wait_for_timeout(wait_after)

            result.title = page.title()
            result.html = page.content()
            result.content = page.inner_text("body")
            page.close()

        except Exception as exc:
            log.error("Fill form failed", extra={"url": url, "error": str(exc)})
            result.error = f"{type(exc).__name__}: {exc}"

        return result

    def take_screenshot(self, url: str, output_path: str, full_page: bool = True) -> str:
        """Take a screenshot of a URL.

        Args:
            url: URL to screenshot.
            output_path: Path to save screenshot.
            full_page: Whether to capture full page.

        Returns:
            Path to saved screenshot.
        """
        result = self.fetch(url, screenshot_path=output_path)
        return result.screenshot_path

    def export_pdf(self, url: str, output_path: str) -> str:
        """Export a URL to PDF.

        Args:
            url: URL to export.
            output_path: Path to save PDF.

        Returns:
            Path to saved PDF.
        """
        result = self.fetch(url, pdf_path=output_path)
        return result.pdf_path

    def get_cookies(self, url: str = "") -> list:
        """Get cookies from browser context.

        Args:
            url: Optional URL to filter cookies.

        Returns:
            List of cookies.
        """
        context = self._get_context()
        if url:
            return context.cookies(url)
        return context.cookies()

    def clear_cookies(self) -> None:
        """Clear all cookies."""
        context = self._get_context()
        context.clear_cookies()
        self._save_cookies()
        log.info("Cookies cleared")

    def close(self) -> None:
        """Close browser and cleanup resources."""
        if self._context:
            self._context.close()
            self._context = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        log.info("Browser fetcher closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def is_browser_available() -> bool:
    """Check if browser fetcher is available."""
    try:
        import playwright
        return True
    except ImportError:
        return False
