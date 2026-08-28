"""Headless browser automation examples.

Demonstrates how to use the browser fetcher for:
- Fetching JavaScript-rendered pages
- Taking screenshots
- Exporting to PDF
- Simulating user interactions (click, fill forms)
- Login state management
"""

from webscout_mcp.browser_fetcher import BrowserConfig, BrowserFetcher, BrowserResult


def example_fetch_js_page():
    """Example: Fetch a JavaScript-rendered page."""
    print("=" * 60)
    print("Example: Fetch JavaScript-Rendered Page")
    print("=" * 60)

    # Initialize browser
    config = BrowserConfig(
        headless=True,
        block_media=True,  # Block videos/audio for faster loading
        wait_for_network_idle=True,
    )
    browser = BrowserFetcher(config=config)

    # Check if Playwright is available
    if not browser.is_available():
        print("Playwright not available. Install with:")
        print("  pip install playwright")
        print("  playwright install chromium")
        browser.close()
        return

    try:
        # Fetch a page with JavaScript rendering
        print("\nFetching https://example.com...")
        result = browser.fetch(
            "https://example.com",
            wait_for_selector="body",  # Wait for body to be visible
            scroll_to_bottom=False,
        )

        if result.error:
            print(f"Error: {result.error}")
        else:
            print(f"  Status: {result.status_code}")
            print(f"  Title: {result.title}")
            print(f"  Content length: {len(result.content)} chars")
            print(f"  Content preview: {result.content[:200]}...")

    finally:
        browser.close()


def example_screenshot():
    """Example: Take a screenshot of a web page."""
    print("\n" + "=" * 60)
    print("Example: Take Screenshot")
    print("=" * 60)

    config = BrowserConfig(headless=True, viewport_width=1920, viewport_height=1080)
    browser = BrowserFetcher(config=config)

    if not browser.is_available():
        print("Playwright not available. Skipping example.")
        browser.close()
        return

    try:
        # Take a full-page screenshot
        output_path = "/tmp/example_screenshot.png"
        print(f"\nTaking screenshot of https://example.com...")
        result = browser.fetch(
            "https://example.com",
            screenshot_path=output_path,
        )

        if result.error:
            print(f"Error: {result.error}")
        else:
            print(f"  Screenshot saved to: {result.screenshot_path}")
            print(f"  Page title: {result.title}")

    finally:
        browser.close()


def example_pdf_export():
    """Example: Export a web page to PDF."""
    print("\n" + "=" * 60)
    print("Example: Export to PDF")
    print("=" * 60)

    config = BrowserConfig(headless=True)
    browser = BrowserFetcher(config=config)

    if not browser.is_available():
        print("Playwright not available. Skipping example.")
        browser.close()
        return

    try:
        # Export to PDF
        output_path = "/tmp/example_page.pdf"
        print(f"\nExporting https://example.com to PDF...")
        result = browser.fetch(
            "https://example.com",
            pdf_path=output_path,
        )

        if result.error:
            print(f"Error: {result.error}")
        else:
            print(f"  PDF saved to: {result.pdf_path}")
            print(f"  Page title: {result.title}")

    finally:
        browser.close()


def example_click_element():
    """Example: Click an element on a page."""
    print("\n" + "=" * 60)
    print("Example: Click Element")
    print("=" * 60)

    config = BrowserConfig(headless=True)
    browser = BrowserFetcher(config=config)

    if not browser.is_available():
        print("Playwright not available. Skipping example.")
        browser.close()
        return

    try:
        # Click a button/link
        print("\nClicking 'More information...' link on example.com...")
        result = browser.click_element(
            "https://example.com",
            "a",  # CSS selector for the link
            wait_after=2000,  # Wait 2 seconds after click
        )

        if result.error:
            print(f"Error: {result.error}")
        else:
            print(f"  New URL: {result.url}")
            print(f"  New title: {result.title}")

    finally:
        browser.close()


def example_fill_form():
    """Example: Fill and submit a form."""
    print("\n" + "=" * 60)
    print("Example: Fill and Submit Form")
    print("=" * 60)

    config = BrowserConfig(headless=True)
    browser = BrowserFetcher(config=config)

    if not browser.is_available():
        print("Playwright not available. Skipping example.")
        browser.close()
        return

    try:
        # Fill a login form (example)
        print("\nFilling login form (example)...")
        result = browser.fill_form(
            "https://example.com/login",
            form_data={
                "#username": "user@example.com",
                "#password": "password123",
            },
            submit_selector="button[type=submit]",
            wait_after=3000,
        )

        if result.error:
            print(f"Error (expected for example.com): {result.error}")
        else:
            print(f"  Form submitted!")
            print(f"  New URL: {result.url}")

    finally:
        browser.close()


def example_cookie_management():
    """Example: Cookie management and login state persistence."""
    print("\n" + "=" * 60)
    print("Example: Cookie Management")
    print("=" * 60)

    config = BrowserConfig(
        headless=True,
        cookie_storage_path="/tmp/webscout_cookies.json",
    )
    browser = BrowserFetcher(config=config)

    if not browser.is_available():
        print("Playwright not available. Skipping example.")
        browser.close()
        return

    try:
        # Fetch a page (cookies are automatically saved)
        print("\nFetching page and saving cookies...")
        result = browser.fetch("https://example.com")

        if not result.error:
            print(f"  Cookies saved: {len(result.cookies)} cookies")

            # Get cookies
            cookies = browser.get_cookies()
            print(f"  Total cookies in context: {len(cookies)}")

            # Clear cookies
            print("\nClearing cookies...")
            browser.clear_cookies()
            print("  Cookies cleared!")

    finally:
        browser.close()


def example_stealth_mode():
    """Example: Anti-detection stealth mode."""
    print("\n" + "=" * 60)
    print("Example: Stealth Mode (Anti-Detection)")
    print("=" * 60)

    # Enable stealth mode to avoid bot detection
    config = BrowserConfig(
        headless=True,
        stealth_mode=True,  # Spoof navigator.webdriver, plugins, languages, etc.
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    browser = BrowserFetcher(config=config)

    if not browser.is_available():
        print("Playwright not available. Skipping example.")
        browser.close()
        return

    try:
        print("\nFetching with stealth mode enabled...")
        print("  - navigator.webdriver = undefined")
        print("  - navigator.plugins = [1,2,3,4,5]")
        print("  - navigator.languages = ['zh-CN', 'zh', 'en']")
        print("  - chrome.runtime = {}")
        print("  - Permissions API spoofed")

        result = browser.fetch("https://example.com")
        if not result.error:
            print(f"\n  Page fetched successfully!")
            print(f"  Title: {result.title}")

    finally:
        browser.close()


def run_all_examples():
    """Run all browser automation examples."""
    print("\n" + "=" * 60)
    print("  Headless Browser Automation Examples")
    print("=" * 60 + "\n")

    example_fetch_js_page()
    example_screenshot()
    example_pdf_export()
    example_click_element()
    example_fill_form()
    example_cookie_management()
    example_stealth_mode()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_examples()
