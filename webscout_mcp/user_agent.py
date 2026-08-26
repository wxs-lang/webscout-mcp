"""Browser fingerprint utilities - random User-Agents and realistic request headers.

Helps avoid being blocked by anti-bot systems by rotating User-Agents and
sending realistic browser headers.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
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

_ACCEPT_VALUES = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
]


@dataclass
class BrowserFingerprint:
    user_agent: str
    accept: str
    accept_language: str
    accept_encoding: str = "gzip, deflate, br"
    sec_ch_ua: str = ""
    sec_ch_ua_mobile: str = "?0"
    sec_ch_ua_platform: str = ""
    upgrade_insecure_requests: str = "1"

    def to_headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": self.accept,
            "Accept-Language": self.accept_language,
            "Accept-Encoding": self.accept_encoding,
            "Upgrade-Insecure-Requests": self.upgrade_insecure_requests,
        }
        if self.sec_ch_ua:
            headers["sec-ch-ua"] = self.sec_ch_ua
            headers["sec-ch-ua-mobile"] = self.sec_ch_ua_mobile
        if self.sec_ch_ua_platform:
            headers["sec-ch-ua-platform"] = self.sec_ch_ua_platform
        return headers


class UserAgentRotator:
    """Rotate User-Agents and browser fingerprints to avoid anti-bot detection."""

    def __init__(self, mobile: bool = False, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)
        self._user_agents = _MOBILE_USER_AGENTS if mobile else _DESKTOP_USER_AGENTS
        self._current_index = self._rng.randint(0, len(self._user_agents) - 1)
        self._mobile = mobile

    def get_user_agent(self) -> str:
        return self._rng.choice(self._user_agents)

    def rotate(self) -> str:
        self._current_index = (self._current_index + 1) % len(self._user_agents)
        return self._user_agents[self._current_index]

    def get_fingerprint(self) -> BrowserFingerprint:
        ua = self.get_user_agent()
        accept = self._rng.choice(_ACCEPT_VALUES)
        accept_language = self._rng.choice(_ACCEPT_LANGUAGES)
        sec_ch_ua = ""
        sec_ch_ua_platform = ""
        if "Chrome/" in ua:
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
        return BrowserFingerprint(
            user_agent=ua, accept=accept, accept_language=accept_language,
            sec_ch_ua=sec_ch_ua, sec_ch_ua_mobile="?1" if self._mobile else "?0",
            sec_ch_ua_platform=sec_ch_ua_platform,
        )

    def get_headers(self) -> dict[str, str]:
        return self.get_fingerprint().to_headers()


def random_user_agent(mobile: bool = False) -> str:
    if mobile:
        return random.choice(_MOBILE_USER_AGENTS)
    return random.choice(_DESKTOP_USER_AGENTS)


def random_headers(mobile: bool = False) -> dict[str, str]:
    rotator = UserAgentRotator(mobile=mobile)
    return rotator.get_headers()
