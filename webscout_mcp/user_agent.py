"""Browser fingerprint utilities - random User-Agents and realistic request headers.
Helps avoid being blocked by anti-bot systems by rotating User-Agents and
sending realistic browser headers that match real browser behavior.

Enhanced features:
- Complete browser fingerprint (User-Agent, Accept, Accept-Language, Sec-Fetch-*, etc.)
- Browser-specific header matching (Chrome, Firefox, Safari)
- Sec-Fetch headers for navigation requests
- Connection, Cache-Control, and other standard headers
- Persistent fingerprint support (same fingerprint for session)
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Optional

_DESKTOP_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

_MOBILE_USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
]

_ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9", "en-GB,en;q=0.9", "zh-CN,zh;q=0.9,en;q=0.8",
    "ja-JP,ja;q=0.9,en;q=0.8", "de-DE,de;q=0.9,en;q=0.8", "fr-FR,fr;q=0.9,en;q=0.8",
]

_CHROME_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
_FIREFOX_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
_SAFARI_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@dataclass
class BrowserFingerprint:
    """Complete browser fingerprint for realistic request headers."""
    user_agent: str
    accept: str
    accept_language: str
    accept_encoding: str = "gzip, deflate, br"
    sec_ch_ua: str = ""
    sec_ch_ua_mobile: str = "?0"
    sec_ch_ua_platform: str = ""
    upgrade_insecure_requests: str = "1"
    sec_fetch_dest: str = "document"
    sec_fetch_mode: str = "navigate"
    sec_fetch_site: str = "none"
    sec_fetch_user: str = "?1"
    connection: str = "keep-alive"
    cache_control: str = "max-age=0"
    browser_type: str = "chrome"  # chrome, firefox, safari

    def to_headers(self) -> dict[str, str]:
        """Convert fingerprint to HTTP headers dictionary."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": self.accept,
            "Accept-Language": self.accept_language,
            "Accept-Encoding": self.accept_encoding,
            "Connection": self.connection,
            "Upgrade-Insecure-Requests": self.upgrade_insecure_requests,
            "Sec-Fetch-Dest": self.sec_fetch_dest,
            "Sec-Fetch-Mode": self.sec_fetch_mode,
            "Sec-Fetch-Site": self.sec_fetch_site,
            "Sec-Fetch-User": self.sec_fetch_user,
        }
        if self.cache_control:
            headers["Cache-Control"] = self.cache_control
        if self.sec_ch_ua:
            headers["sec-ch-ua"] = self.sec_ch_ua
            headers["sec-ch-ua-mobile"] = self.sec_ch_ua_mobile
        if self.sec_ch_ua_platform:
            headers["sec-ch-ua-platform"] = self.sec_ch_ua_platform
        return headers

    def get_ajax_headers(self) -> dict[str, str]:
        """Get headers for AJAX/XHR requests (different Sec-Fetch values)."""
        headers = self.to_headers()
        headers["Sec-Fetch-Dest"] = "empty"
        headers["Sec-Fetch-Mode"] = "cors"
        headers["Sec-Fetch-Site"] = "same-origin"
        headers.pop("Sec-Fetch-User", None)
        headers.pop("Upgrade-Insecure-Requests", None)
        headers["Accept"] = "application/json, text/plain, */*"
        headers["X-Requested-With"] = "XMLHttpRequest"
        return headers


class UserAgentRotator:
    """Rotate User-Agents and browser fingerprints to avoid anti-bot detection.

    Supports persistent fingerprints (same fingerprint for session) and
    random rotation for each request.
    """

    def __init__(
        self,
        mobile: bool = False,
        seed: Optional[int] = None,
        persistent: bool = False,
    ) -> None:
        self._rng = random.Random(seed)
        self._user_agents = _MOBILE_USER_AGENTS if mobile else _DESKTOP_USER_AGENTS
        self._current_index = self._rng.randint(0, len(self._user_agents) - 1)
        self._mobile = mobile
        self._persistent = persistent
        self._persistent_fingerprint: Optional[BrowserFingerprint] = None

    def get_user_agent(self) -> str:
        """Get a random User-Agent string."""
        return self._rng.choice(self._user_agents)

    def rotate(self) -> str:
        """Rotate to next User-Agent in sequence."""
        self._current_index = (self._current_index + 1) % len(self._user_agents)
        return self._user_agents[self._current_index]

    def _detect_browser_type(self, ua: str) -> str:
        """Detect browser type from User-Agent string."""
        if "Firefox/" in ua:
            return "firefox"
        elif "Safari/" in ua and "Chrome/" not in ua:
            return "safari"
        else:
            return "chrome"

    def _get_accept_for_browser(self, browser_type: str) -> str:
        """Get Accept header value for specific browser type."""
        if browser_type == "firefox":
            return _FIREFOX_ACCEPT
        elif browser_type == "safari":
            return _SAFARI_ACCEPT
        else:
            return _CHROME_ACCEPT

    def get_fingerprint(self) -> BrowserFingerprint:
        """Generate a complete browser fingerprint.

        If persistent mode is enabled, returns the same fingerprint for the session.
        """
        if self._persistent and self._persistent_fingerprint:
            return self._persistent_fingerprint

        ua = self.get_user_agent()
        browser_type = self._detect_browser_type(ua)
        accept = self._get_accept_for_browser(browser_type)
        accept_language = self._rng.choice(_ACCEPT_LANGUAGES)

        sec_ch_ua = ""
        sec_ch_ua_platform = ""

        if browser_type == "chrome":
            try:
                version = ua.split("Chrome/")[1].split(".")[0]
                sec_ch_ua = f'"Not_A Brand";v="8", "Chromium";v="{version}", "Google Chrome";v="{version}"'
            except (IndexError, ValueError):
                sec_ch_ua = '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'

            if "Windows" in ua:
                sec_ch_ua_platform = '"Windows"'
            elif "Macintosh" in ua:
                sec_ch_ua_platform = '"macOS"'
            elif "Linux" in ua and "Android" not in ua:
                sec_ch_ua_platform = '"Linux"'
            elif "Android" in ua:
                sec_ch_ua_platform = '"Android"'

        fingerprint = BrowserFingerprint(
            user_agent=ua,
            accept=accept,
            accept_language=accept_language,
            sec_ch_ua=sec_ch_ua,
            sec_ch_ua_mobile="?1" if self._mobile else "?0",
            sec_ch_ua_platform=sec_ch_ua_platform,
            browser_type=browser_type,
        )

        if self._persistent:
            self._persistent_fingerprint = fingerprint

        return fingerprint

    def get_headers(self) -> dict[str, str]:
        """Get HTTP headers from a random browser fingerprint."""
        return self.get_fingerprint().to_headers()

    def get_ajax_headers(self) -> dict[str, str]:
        """Get AJAX/XHR headers from a random browser fingerprint."""
        return self.get_fingerprint().get_ajax_headers()


def random_user_agent(mobile: bool = False) -> str:
    """Get a random User-Agent string."""
    if mobile:
        return random.choice(_MOBILE_USER_AGENTS)
    return random.choice(_DESKTOP_USER_AGENTS)


def random_headers(mobile: bool = False) -> dict[str, str]:
    """Get random realistic browser headers."""
    rotator = UserAgentRotator(mobile=mobile)
    return rotator.get_headers()


def random_ajax_headers(mobile: bool = False) -> dict[str, str]:
    """Get random AJAX/XHR browser headers."""
    rotator = UserAgentRotator(mobile=mobile)
    return rotator.get_ajax_headers()
