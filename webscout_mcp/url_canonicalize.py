"""Conservative URL canonicalization for WebScout v1.3.0.

Goals:
  * Collapse trivial URL variants that point to the same resource
    (fragment, scheme/host case, common tracking parameters).
  * Never merge two genuinely different pages.
  * Never touch auth-sensitive query parameters or business-significant
    parameters.

This is intentionally conservative: if we are not sure a parameter is a
tracking token, we keep it.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Parameters that are universally understood as analytics / click-tracking.
# Lower-case, exact match. Anything not on this list is preserved.
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
        "hsCtaTracking",
        "ref",
        "ref_src",
        "ref_url",
    }
)


def canonicalize_url(url: str) -> str:
    """Return a conservative canonical form of *url*.

    Rules applied:
      * fragment is dropped (``#section``)
      * scheme and host are lower-cased
      * port is preserved if present
      * known tracking query parameters are removed
      * other query parameters are preserved in their original order
      * path is left as-is (no trailing-slash rewriting, no percent-decoding)
      * credentials (user:pass@) are preserved verbatim — we must not
        rewrite auth URLs
    """
    if not url or not isinstance(url, str):
        return url or ""
    try:
        p = urlparse(url)
    except ValueError:
        return url

    scheme = (p.scheme or "").lower()
    netloc = p.netloc
    # Lower-case host but keep credentials and port intact.
    if "@" in netloc:
        cred, _, hostport = netloc.rpartition("@")
    else:
        cred, hostport = "", netloc
    if ":" in hostport:
        host, _, port = hostport.partition(":")
        host = host.lower()
        hostport = f"{host}:{port}"
    else:
        hostport = hostport.lower()
    netloc = f"{cred}@{hostport}" if cred else hostport

    # Drop fragment.
    fragment = ""

    # Filter query string.
    pairs = parse_qsl(p.query, keep_blank_values=True)
    kept = [(k, v) for (k, v) in pairs if k.lower() not in _TRACKING_PARAMS]
    query = urlencode(kept, doseq=True)

    return urlunparse((scheme, netloc, p.path, p.params, query, fragment))


def canonical_url_key(url: str) -> str:
    """A hashable key for duplicate detection. Same as canonicalize_url."""
    return canonicalize_url(url)
