"""Utility helpers: rate limiter, URL normalisation, content detection."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Optional
from urllib.parse import urlparse, urlunparse


class TokenBucket:
    """An async token-bucket rate limiter, keyed by domain.

    Each domain gets its own bucket so that a slow site doesn't block a fast
    one.  Tokens refill at ``rate`` per second up to ``burst`` capacity.
    """

    def __init__(self, rate: float = 2.0, burst: int = 5):
        self.rate = rate
        self.burst = burst
        self._buckets: dict[str, float] = defaultdict(lambda: float(burst))
        self._last_refill: dict[str, float] = defaultdict(time.monotonic)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @staticmethod
    def _domain(url: str) -> str:
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return url

    async def acquire(self, url: str) -> None:
        """Block until a token is available for ``url``'s domain."""
        domain = self._domain(url)
        async with self._locks[domain]:
            now = time.monotonic()
            elapsed = now - self._last_refill[domain]
            self._buckets[domain] = min(
                self.burst,
                self._buckets[domain] + elapsed * self.rate,
            )
            self._last_refill[domain] = now

            if self._buckets[domain] < 1.0:
                wait = (1.0 - self._buckets[domain]) / self.rate
                await asyncio.sleep(wait)
                now = time.monotonic()
                elapsed = now - self._last_refill[domain]
                self._buckets[domain] = min(
                    self.burst,
                    self._buckets[domain] + elapsed * self.rate,
                )
                self._last_refill[domain] = now

            self._buckets[domain] -= 1.0


def normalize_url(url: str) -> str:
    """Normalise a URL: lowercase scheme+host, strip fragment, default ports."""
    try:
        parsed = urlparse(url.strip())
        scheme = parsed.scheme.lower() or "https"
        netloc = parsed.netloc.lower()
        # Strip default ports
        if scheme == "http" and netloc.endswith(":80"):
            netloc = netloc[:-3]
        elif scheme == "https" and netloc.endswith(":443"):
            netloc = netloc[:-4]
        path = parsed.path or "/"
        # Collapse duplicate slashes
        while "//" in path:
            path = path.replace("//", "/")
        return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))
    except Exception:
        return url


def is_valid_url(url: str) -> bool:
    """Return True if ``url`` looks like a valid http(s) URL."""
    try:
        parsed = urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def truncate_text(text: str, max_chars: int = 8000) -> str:
    """Truncate text to ``max_chars``, appending a note if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... [truncated, {len(text) - max_chars} chars omitted]"
