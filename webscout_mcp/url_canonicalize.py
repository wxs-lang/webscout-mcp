"""Conservative URL canonicalization for WebScout v1.3.0 Phase 1.1.

Canonicalization here is used ONLY for identity / dedup / grouping. It
must never be used as a real request URL. Real request URLs are always
the caller's original string — this module never rewrites them.

Goals:
  * Collapse trivial URL variants that point to the same resource
    (fragment, scheme/host case, well-known tracking parameters).
  * Never merge two genuinely different pages.
  * Never touch auth-sensitive or business-significant parameters.
  * Strip credentials from the *identity* (so they don't leak into logs
    or dedup sets).
"""

from __future__ import annotations

import ipaddress
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# High-confidence, industry-standard tracking parameters. Lower-cased exact
# match. Ambiguous names (e.g. ``ref``) are deliberately NOT here.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_name",
        "utm_cid",
        "utm_reader",
        "utm_referrer",
        "fbclid",
        "gclid",
        "gclsrc",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "hsctatracking",
    }
)


def canonical_url_key(url: str) -> str:
    """Identity key for dedup / grouping. Does NOT include credentials.

    Use this for equality / grouping only. Never use it as a request URL.
    """
    if not url or not isinstance(url, str):
        return ""
    try:
        p = urlparse(url)
    except ValueError:
        return url

    scheme = (p.scheme or "").lower()
    host = (p.hostname or "").lower()
    if not host:
        return ""
    # Use p.port (parsed safely, IPv6-aware) rather than string splitting.
    port = p.port
    # IPv6 literals need brackets in netloc.
    try:
        is_v6 = isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address)
    except ValueError:
        is_v6 = False
    if is_v6:
        netloc = f"[{host}]:{port}" if port else f"[{host}]"
    else:
        netloc = f"{host}:{port}" if port else host

    # Drop fragment, filter tracking params, preserve everything else.
    pairs = parse_qsl(p.query, keep_blank_values=True)
    kept = [(k, v) for (k, v) in pairs if k.lower() not in _TRACKING_PARAMS]
    query = urlencode(kept, doseq=True)

    return urlunparse((scheme, netloc, p.path, p.params, query, ""))


def canonicalize_url(url: str) -> str:
    """Alias for :func:`canonical_url_key`.

    Kept for backwards compatibility with Phase 1 callers. New code should
    use ``canonical_url_key`` explicitly to make the intent clear.
    """
    return canonical_url_key(url)
