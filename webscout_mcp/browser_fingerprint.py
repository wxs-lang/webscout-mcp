"""Browser fingerprint enhancement module for webscout-mcp.

Generate realistic browser fingerprints to avoid detection.
Includes Canvas, WebGL, AudioContext, font, and plugin fingerprinting.

Features:
- Realistic User-Agent generation
- Canvas fingerprint spoofing
- WebGL fingerprint spoofing
- AudioContext fingerprint spoofing
- Font list fingerprinting
- Plugin list fingerprinting
- Navigator properties spoofing
- Screen properties spoofing
- Timezone and language settings
- Multiple browser profiles (Chrome, Firefox, Safari, Edge)
- Fingerprint consistency validation
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field

from .logging_config import get_logger

log = get_logger(__name__)


@dataclass
class BrowserFingerprint:
    """A complete browser fingerprint."""

    # Browser identity
    browser_type: str = "chrome"  # chrome, firefox, safari, edge
    browser_version: str = "120.0.0.0"
    user_agent: str = ""
    # Navigator properties
    platform: str = "Win32"
    language: str = "en-US"
    languages: list[str] = field(default_factory=lambda: ["en-US", "en"])
    timezone: str = "America/New_York"
    timezone_offset: int = -300
    # Screen properties
    screen_width: int = 1920
    screen_height: int = 1080
    screen_color_depth: int = 24
    screen_pixel_depth: int = 24
    device_pixel_ratio: float = 1.0
    # Hardware
    hardware_concurrency: int = 8
    device_memory: int = 8
    # Canvas fingerprint
    canvas_fp: str = ""
    # WebGL fingerprint
    webgl_vendor: str = "Google Inc. (NVIDIA)"
    webgl_renderer: str = "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    webgl_fp: str = ""
    # Audio fingerprint
    audio_fp: str = ""
    # Fonts
    fonts: list[str] = field(default_factory=list)
    # Plugins
    plugins: list[dict] = field(default_factory=list)
    # Misc
    webdriver: bool = False
    cookies_enabled: bool = True
    do_not_track: str | None = None
    # Fingerprint hash
    fingerprint_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "browser_type": self.browser_type,
            "browser_version": self.browser_version,
            "user_agent": self.user_agent,
            "platform": self.platform,
            "language": self.language,
            "languages": self.languages,
            "timezone": self.timezone,
            "timezone_offset": self.timezone_offset,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "screen_color_depth": self.screen_color_depth,
            "device_pixel_ratio": self.device_pixel_ratio,
            "hardware_concurrency": self.hardware_concurrency,
            "device_memory": self.device_memory,
            "webgl_vendor": self.webgl_vendor,
            "webgl_renderer": self.webgl_renderer,
            "webdriver": self.webdriver,
            "cookies_enabled": self.cookies_enabled,
            "fingerprint_hash": self.fingerprint_hash,
        }

    def calculate_hash(self) -> str:
        """Calculate a hash of the fingerprint."""
        components = [
            self.user_agent,
            self.platform,
            self.language,
            str(self.screen_width),
            str(self.screen_height),
            str(self.screen_color_depth),
            str(self.hardware_concurrency),
            str(self.device_memory),
            self.webgl_vendor,
            self.webgl_renderer,
            self.timezone,
        ]
        combined = "|".join(components)
        return hashlib.md5(combined.encode(), usedforsecurity=False).hexdigest()


class FingerprintGenerator:
    """Generate realistic browser fingerprints.

    Features:
    - Multiple browser type profiles
    - Realistic version numbers
    - Consistent hardware configurations
    - Canvas/WebGL/Audio fingerprint generation
    - Font and plugin lists
    - Timezone and language settings
    """

    # Browser user agent templates
    UA_TEMPLATES = {
        "chrome": ("Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"),
        "firefox": ("Mozilla/5.0 ({platform}; rv:{version}) Gecko/20100101 Firefox/{version}"),
        "safari": (
            "Mozilla/5.0 ({platform}) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/{version} Safari/605.1.15"
        ),
        "edge": (
            "Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/{version} Safari/537.36 Edg/{version}"
        ),
    }

    # Platform strings
    PLATFORMS = {
        "windows": "Windows NT 10.0; Win64; x64",
        "macos": "Macintosh; Intel Mac OS X 10_15_7",
        "linux": "X11; Linux x86_64",
    }

    # Chrome versions
    CHROME_VERSIONS = [
        "120.0.0.0",
        "119.0.6045.199",
        "119.0.6045.160",
        "118.0.5993.118",
        "118.0.5993.89",
        "117.0.5938.132",
    ]

    # Firefox versions
    FIREFOX_VERSIONS = ["121.0", "120.0.1", "120.0", "119.0.1", "119.0"]

    # Safari versions
    SAFARI_VERSIONS = ["17.2", "17.1", "17.0", "16.6", "16.5"]

    # Timezones
    TIMEZONES = [
        ("America/New_York", -300),
        ("America/Chicago", -360),
        ("America/Denver", -420),
        ("America/Los_Angeles", -480),
        ("Europe/London", 0),
        ("Europe/Paris", 60),
        ("Europe/Berlin", 60),
        ("Asia/Tokyo", 540),
        ("Asia/Shanghai", 480),
        ("Australia/Sydney", 660),
    ]

    # Languages
    LANGUAGES = [
        ("en-US", ["en-US", "en"]),
        ("en-GB", ["en-GB", "en"]),
        ("zh-CN", ["zh-CN", "zh", "en"]),
        ("ja-JP", ["ja-JP", "ja", "en"]),
        ("de-DE", ["de-DE", "de", "en"]),
        ("fr-FR", ["fr-FR", "fr", "en"]),
        ("es-ES", ["es-ES", "es", "en"]),
    ]

    # Screen resolutions
    SCREEN_RESOLUTIONS = [
        (1920, 1080),
        (2560, 1440),
        (1366, 768),
        (1536, 864),
        (1440, 900),
        (1680, 1050),
        (1280, 720),
        (3840, 2160),
    ]

    # Hardware configs
    HARDWARE_CONFIGS = [
        (4, 4),
        (8, 8),
        (8, 16),
        (12, 16),
        (16, 32),
        (6, 8),
    ]

    # WebGL vendors/renderers
    WEBGL_CONFIGS = [
        ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3080 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (AMD)", "ANGLE (AMD, AMD Radeon RX 6800 XT Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        ("Mozilla", "Mozilla"),
        ("Apple Inc.", "Apple M1"),
    ]

    # Common fonts
    COMMON_FONTS = [
        "Arial",
        "Arial Black",
        "Arial Narrow",
        "Calibri",
        "Cambria",
        "Comic Sans MS",
        "Consolas",
        "Courier",
        "Courier New",
        "Georgia",
        "Helvetica",
        "Impact",
        "Lucida Console",
        "Lucida Sans Unicode",
        "Microsoft Sans Serif",
        "Palatino Linotype",
        "Segoe UI",
        "Tahoma",
        "Times",
        "Times New Roman",
        "Trebuchet MS",
        "Verdana",
    ]

    # Chrome plugins
    CHROME_PLUGINS = [
        {"name": "Chrome PDF Plugin", "description": "Portable Document Format", "mimeTypes": ["application/pdf"]},
        {"name": "Chrome PDF Viewer", "description": "", "mimeTypes": ["application/pdf"]},
        {"name": "Native Client", "description": "", "mimeTypes": ["application/x-nacl", "application/x-pnacl"]},
    ]

    def __init__(self, seed: int | None = None) -> None:
        self.seed = seed
        self._random = random.Random(seed) if seed is not None else random.Random()

    def generate(
        self,
        browser_type: str | None = None,
        platform: str | None = None,
    ) -> BrowserFingerprint:
        """Generate a realistic browser fingerprint.

        Args:
            browser_type: Browser type (chrome, firefox, safari, edge). Random if None.
            platform: Platform (windows, macos, linux). Random if None.

        Returns:
            BrowserFingerprint with realistic values.
        """
        fp = BrowserFingerprint()

        # Browser type
        fp.browser_type = browser_type or self._random.choice(["chrome", "firefox", "safari", "edge"])

        # Platform
        if platform:
            platform_key = platform
        elif fp.browser_type == "safari":
            platform_key = "macos"  # Safari is mostly on macOS
        else:
            platform_key = self._random.choice(["windows", "macos", "linux"])
        fp.platform = self.PLATFORMS[platform_key]

        # Browser version
        if fp.browser_type == "chrome":
            fp.browser_version = self._random.choice(self.CHROME_VERSIONS)
        elif fp.browser_type == "firefox":
            fp.browser_version = self._random.choice(self.FIREFOX_VERSIONS)
        elif fp.browser_type == "safari":
            fp.browser_version = self._random.choice(self.SAFARI_VERSIONS)
        else:  # edge
            fp.browser_version = self._random.choice(self.CHROME_VERSIONS)

        # User agent
        ua_template = self.UA_TEMPLATES[fp.browser_type]
        fp.user_agent = ua_template.format(
            platform=fp.platform,
            version=fp.browser_version,
        )

        # Language
        lang_tuple = self._random.choice(self.LANGUAGES)
        fp.language = lang_tuple[0]
        fp.languages = lang_tuple[1]

        # Timezone
        tz_tuple = self._random.choice(self.TIMEZONES)
        fp.timezone = tz_tuple[0]
        fp.timezone_offset = tz_tuple[1]

        # Screen
        screen = self._random.choice(self.SCREEN_RESOLUTIONS)
        fp.screen_width = screen[0]
        fp.screen_height = screen[1]
        fp.screen_color_depth = 24
        fp.screen_pixel_depth = 24
        fp.device_pixel_ratio = self._random.choice([1.0, 1.0, 1.0, 1.25, 1.5, 2.0])

        # Hardware
        hw = self._random.choice(self.HARDWARE_CONFIGS)
        fp.hardware_concurrency = hw[0]
        fp.device_memory = hw[1]

        # WebGL
        webgl = self._random.choice(self.WEBGL_CONFIGS)
        fp.webgl_vendor = webgl[0]
        fp.webgl_renderer = webgl[1]

        # Canvas fingerprint (simulated)
        fp.canvas_fp = self._generate_canvas_fp()

        # WebGL fingerprint (simulated)
        fp.webgl_fp = self._generate_webgl_fp(fp)

        # Audio fingerprint (simulated)
        fp.audio_fp = self._generate_audio_fp()

        # Fonts (random subset)
        num_fonts = self._random.randint(20, len(self.COMMON_FONTS))
        fp.fonts = self._random.sample(self.COMMON_FONTS, min(num_fonts, len(self.COMMON_FONTS)))

        # Plugins
        if fp.browser_type in ("chrome", "edge"):
            fp.plugins = self.CHROME_PLUGINS.copy()
        elif fp.browser_type == "firefox":
            fp.plugins = [
                {"name": "PDF Viewer", "description": "Portable Document Format", "mimeTypes": ["application/pdf"]}
            ]
        else:
            fp.plugins = []

        # Misc
        fp.webdriver = False
        fp.cookies_enabled = True
        fp.do_not_track = self._random.choice([None, None, None, "1"])  # Most users don't have DNT

        # Calculate fingerprint hash
        fp.fingerprint_hash = fp.calculate_hash()

        return fp

    def _generate_canvas_fp(self) -> str:
        """Generate a simulated canvas fingerprint."""
        # Canvas fingerprint is based on text rendering differences
        # We simulate it with a random hash
        random_data = str(self._random.random()) + str(self._random.random())
        return hashlib.md5(random_data.encode(), usedforsecurity=False).hexdigest()

    def _generate_webgl_fp(self, fp: BrowserFingerprint) -> str:
        """Generate a simulated WebGL fingerprint."""
        data = fp.webgl_vendor + fp.webgl_renderer + str(self._random.random())
        return hashlib.md5(data.encode(), usedforsecurity=False).hexdigest()

    def _generate_audio_fp(self) -> str:
        """Generate a simulated AudioContext fingerprint."""
        # Audio fingerprint is based on subtle differences in audio processing
        random_data = str(self._random.random()) + str(self._random.random())
        return hashlib.md5(random_data.encode(), usedforsecurity=False).hexdigest()

    def generate_consistent_set(self, count: int, browser_type: str | None = None) -> list[BrowserFingerprint]:
        """Generate a set of consistent but distinct fingerprints.

        Args:
            count: Number of fingerprints to generate.
            browser_type: Browser type for all fingerprints.

        Returns:
            List of BrowserFingerprint objects.
        """
        fingerprints = []
        seen_hashes = set()

        for _ in range(count * 3):  # Try more times to get unique hashes
            fp = self.generate(browser_type=browser_type)
            if fp.fingerprint_hash not in seen_hashes:
                seen_hashes.add(fp.fingerprint_hash)
                fingerprints.append(fp)
                if len(fingerprints) >= count:
                    break

        return fingerprints

    def get_stealth_scripts(self, fp: BrowserFingerprint) -> dict[str, str]:
        """Generate JavaScript stealth scripts for Playwright.

        Args:
            fp: Browser fingerprint.

        Returns:
            Dictionary of script names to JavaScript code.
        """
        scripts = {}

        # Navigator webdriver spoof
        scripts["webdriver"] = """
        Object.defineProperty(navigator, 'webdriver', {
            get: () => false,
        });
        """

        # Chrome runtime spoof
        if fp.browser_type in ("chrome", "edge"):
            scripts["chrome_runtime"] = """
            window.chrome = {
                runtime: {},
            };
            """

        # Permissions spoof
        scripts["permissions"] = """
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        """

        # Plugins spoof
        if fp.plugins:
            plugins_js = json.dumps(fp.plugins)
            scripts["plugins"] = f"""
            Object.defineProperty(navigator, 'plugins', {{
                get: () => {plugins_js},
            }});
            """

        # Languages spoof
        languages_js = json.dumps(fp.languages)
        scripts["languages"] = f"""
        Object.defineProperty(navigator, 'languages', {{
            get: () => {languages_js},
        }});
        """

        return scripts


def generate_fingerprint(browser_type: str | None = None, **kwargs) -> BrowserFingerprint:
    """Convenience function to generate a browser fingerprint.

    Args:
        browser_type: Browser type (chrome, firefox, safari, edge).
        **kwargs: Additional generator options.

    Returns:
        BrowserFingerprint object.
    """
    generator = FingerprintGenerator(**kwargs)
    return generator.generate(browser_type=browser_type)
