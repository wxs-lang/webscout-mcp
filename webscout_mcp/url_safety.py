"""SSRF / private-network guard for outbound fetch.

Single source of truth for "is this URL safe to ask a browser sidecar to
fetch on our behalf". Implements the v1.2.3 hardening:

  - only http/https schemes
  - literal IPv4/IPv6 hosts are checked against loopback / private /
    link-local / reserved / multicast ranges
  - hostnames are resolved via DNS and every A/AAAA result is checked —
    this defeats "hostname looks public but resolves to 127.0.0.1" tricks
  - cloud metadata endpoints (169.254.169.254, metadata.google.internal)
    are explicitly covered
  - redirect chains are re-checked: the caller should call
    :func:`assert_redirect_chain_safe` with a short httpx probe so a
    30x-to-internal hop cannot bypass the initial check

When ``allow_private`` is True (opt-in only), all of the above is skipped.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

# Hostnames that always resolve to metadata / internal services. These are
# checked by string match before DNS to avoid depending on DNS config.
_METADATA_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.goog",
    "169.254.169.254.nip.io",
}

_ALLOWED_SCHEMES = {"http", "https"}


@dataclass
class UrlSafetyResult:
    safe: bool
    reason: str = ""
    resolved_ips: list[str] | None = None


def _ip_is_public(ip_str: str) -> bool:
    """Return True if the IP is a routable public address."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if getattr(ip, "is_site_local", False):
        return False
    return True


def _resolve_host(host: str) -> list[str]:
    """Resolve all A/AAAA records for a hostname. Failures -> []."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    ips: list[str] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        # Strip zone id for IPv6 link-local
        if "%" in ip:
            ip = ip.split("%", 1)[0]
        ips.append(ip)
    return sorted(set(ips))


def check_url_safe(url: str, *, allow_private: bool = False) -> UrlSafetyResult:
    """Check a single URL. Does not follow redirects."""
    if allow_private:
        return UrlSafetyResult(safe=True, reason="allow_private set")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return UrlSafetyResult(False, f"scheme '{scheme}' not allowed (only http/https)")

    host = parsed.hostname
    if not host:
        return UrlSafetyResult(False, "URL has no host")

    host_l = host.lower().rstrip(".")
    if host_l in _METADATA_HOSTNAMES:
        return UrlSafetyResult(False, f"metadata endpoint '{host}' blocked")

    # If it is already a literal IP, check directly.
    try:
        ipaddress.ip_address(host_l)
        literal = True
    except ValueError:
        literal = False

    if literal:
        if not _ip_is_public(host_l):
            return UrlSafetyResult(False, f"host {host_l} is not a public address", [host_l])
        return UrlSafetyResult(True, "literal public ip", [host_l])

    ips = _resolve_host(host_l)
    if not ips:
        return UrlSafetyResult(False, f"DNS resolution failed for {host}")
    bad = [ip for ip in ips if not _ip_is_public(ip)]
    if bad:
        return UrlSafetyResult(
            False,
            f"host {host} resolves to non-public address(es): {','.join(bad[:3])}",
            ips,
        )
    return UrlSafetyResult(True, "ok", ips)


async def assert_redirect_chain_safe(
    url: str,
    *,
    allow_private: bool = False,
    timeout: float = 5.0,
) -> UrlSafetyResult:
    """Probe a URL with redirects enabled and re-check every hop.

    Uses a streaming HEAD/GET so we never download a full page. If any hop
    redirects to a private/link-local/metadata address, the whole chain is
    rejected. Network errors are treated as "safe to proceed" — the
    underlying fetch will surface the real error.
    """
    first = check_url_safe(url, allow_private=allow_private)
    if not first.safe:
        return first
    if allow_private:
        return first

    try:
        async with (
            httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": "webscout-mcp-urlcheck/1.0"},
            ) as client,
            client.stream("GET", url) as resp,
        ):
            history = [str(resp.request.url)] + [str(r.request.url) for r in resp.history]
            for hop in history:
                r = check_url_safe(hop, allow_private=False)
                if not r.safe:
                    return r
    except (httpx.HTTPError, OSError):
        # We couldn't probe — let the real fetch surface the error.
        return UrlSafetyResult(True, "redirect probe skipped (network error)")

    return UrlSafetyResult(True, "redirect chain ok")
