"""Utility helpers: rate limiter, URL normalisation, content detection, security checks."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections import defaultdict
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


# --- URL Security (SSRF Protection) ---

# Sensitive ports that should never be accessed via web scraping
SENSITIVE_PORTS = {
    22,  # SSH
    23,  # Telnet
    25,  # SMTP
    53,  # DNS
    110,  # POP3
    143,  # IMAP
    3306,  # MySQL
    5432,  # PostgreSQL
    6379,  # Redis
    27017,  # MongoDB
    9200,  # Elasticsearch
    11211,  # Memcached
    2375,  # Docker
    2376,  # Docker TLS
}


def is_safe_url(url: str, *, allow_private: bool = False) -> tuple[bool, str]:
    """Check if a URL is safe to fetch (SSRF protection).

    Args:
        url: The URL to check.
        allow_private: If True, allow private/internal IP addresses (not recommended).

    Returns:
        A tuple of (is_safe, reason). If is_safe is False, reason explains why.
    """
    if not is_valid_url(url):
        return False, "Invalid URL or unsupported scheme"

    try:
        parsed = urlparse(url.strip())
        hostname = parsed.hostname or ""
        port = parsed.port

        # Check for localhost variants
        localhost_variants = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
        if hostname.lower() in localhost_variants:
            if not allow_private:
                return False, f"Access to localhost is blocked: {hostname}"

        # Check sensitive ports
        if port and port in SENSITIVE_PORTS:
            return False, f"Access to sensitive port {port} is blocked"

        # Resolve hostname and check for private IPs
        if not allow_private and hostname.lower() not in localhost_variants:
            try:
                addr_infos = socket.getaddrinfo(hostname, None)
                for addr_info in addr_infos:
                    ip = addr_info[4][0]
                    try:
                        ip_obj = ipaddress.ip_address(ip)
                        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
                            return False, f"Hostname resolves to private/internal IP: {ip}"
                    except ValueError:
                        continue
            except socket.gaierror:
                # DNS resolution failed - let the fetcher handle this error
                pass

        return True, "URL is safe"
    except Exception as exc:
        return False, f"URL validation error: {exc}"


def extract_domain(url: str) -> str:
    """Extract the domain from a URL (without port)."""
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""
