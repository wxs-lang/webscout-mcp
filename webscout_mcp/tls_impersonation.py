"""TLS impersonation as a fast layer between plain HTTP and a browser.

## Why this belongs in the pipeline

Measured on the sites a headless browser could not open:

    reuters.com   401 (httpx) -> 403 (headless chromium) -> 200 + 3713 chars of real
                  article via curl_cffi with a safari TLS fingerprint, in 955ms
    medium.com    403 -> 200 but only 149 chars of navigation (SPA, needs rendering)

So TLS impersonation is not a universal key. It fixes the sites that block on the
handshake and nothing else, and it costs one request instead of a 3-6s browser
launch. That is exactly the shape of a good intermediate step: try the cheap
impersonation first, escalate to the browser only if content is still missing.

## The deployment hazard it has to handle

libcurl cannot open a CA bundle under a non-ASCII path:

    curl: (77) error setting certificate verify locations:
    CAfile: D:\\测试\\_tls\\Lib\\site-packages\\certifi\\cacert.pem

Verified: the same request succeeds once the bundle is copied to an ASCII path.
Any user whose Python lives under a non-ASCII directory hits this, and the error
reads like a network failure. This module copies the bundle to an ASCII temp
location when needed.

## Version note

curl_cffi 0.17.0 failed with the same SSL error even where 0.15.0 worked; the
ASCII-path fix resolves both, but the dependency is pinned below 0.17 until the
newer line is verified.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Ordered by observed effectiveness, not preference. Different targets key on
# different fingerprints: reddit returns 166KB to chrome131 and 8KB to safari,
# while reuters returns 1.3MB to safari and 774 bytes to chrome.
IMPERSONATION_PROFILES: tuple[str, ...] = ("safari17_0", "chrome131", "chrome124")

_ca_bundle: str | None = None
_available: bool | None = None


def _is_ascii(path: str) -> bool:
    return all(ord(ch) < 128 for ch in path)


def _ascii_ca_bundle() -> str | None:
    """Path to a CA bundle libcurl can actually open.

    libcurl is a C library using the system ANSI API on Windows, so a bundle under
    ``D:\\测试\\...`` fails with curl error 77. Copy it somewhere ASCII.
    """
    global _ca_bundle
    if _ca_bundle is not None:
        return _ca_bundle or None
    try:
        import certifi
    except ImportError:
        _ca_bundle = ""
        return None

    source = certifi.where()
    if _is_ascii(source):
        _ca_bundle = source
        return source

    target_dir = Path(tempfile.gettempdir()) / "webscout-ca"
    target = target_dir / "cacert.pem"
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.stat().st_mtime < Path(source).stat().st_mtime:
            shutil.copy2(source, target)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        log.warning("could not stage CA bundle at %s: %s", target, exc)
        _ca_bundle = ""
        return None

    if not _is_ascii(str(target)):  # pragma: no cover - temp dir is ASCII on Windows
        log.warning("temp dir is not ASCII either (%s); TLS impersonation disabled", target)
        _ca_bundle = ""
        return None

    log.debug("staged CA bundle for libcurl at %s (source path was non-ASCII)", target)
    _ca_bundle = str(target)
    return _ca_bundle


def is_available() -> bool:
    """True when curl_cffi is importable and a usable CA bundle exists."""
    global _available
    if _available is not None:
        return _available
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        _available = False
        return False
    _available = _ascii_ca_bundle() is not None
    return _available


def fetch_impersonated(
    url: str,
    *,
    timeout: float = 30.0,
    profiles: tuple[str, ...] = IMPERSONATION_PROFILES,
) -> tuple[int, str, str]:
    """GET ``url`` with a real browser TLS fingerprint.

    Returns (status_code, html_text, profile_used). Tries each profile until one
    returns a non-error status, because the right fingerprint is target-dependent.

    Returns (0, "", "") when impersonation is unavailable or every profile fails.
    """
    if not is_available():
        return 0, "", ""

    from curl_cffi import requests as curl_requests

    ca = _ascii_ca_bundle()
    last_status = 0
    for profile in profiles:
        try:
            resp = curl_requests.get(
                url,
                impersonate=profile,
                timeout=timeout,
                allow_redirects=True,
                verify=ca,
            )
        except Exception as exc:  # noqa: BLE001 - any transport failure means "try next"
            log.debug("impersonation %s failed for %s: %s", profile, url, exc)
            continue

        body = resp.text or ""
        if resp.status_code < 400 and body:
            return resp.status_code, body, profile
        last_status = resp.status_code
        log.debug("impersonation %s -> %s for %s", profile, resp.status_code, url)

    return last_status, "", ""


def describe() -> dict[str, Any]:
    """Diagnostics for health output."""
    return {
        "available": is_available(),
        "ca_bundle": _ca_bundle or None,
        "profiles": list(IMPERSONATION_PROFILES),
    }
