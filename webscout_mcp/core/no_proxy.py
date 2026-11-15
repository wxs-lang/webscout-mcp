"""Make the process environment safe for httpx client construction.

httpx <0.29 parses each NO_PROXY entry into an ``all://...`` mount key at
AsyncClient construction. A bracketed IPv6 literal ("[::1]") fails its
ipaddress check, falls through to the wildcard branch, and produces
``all://*[::1]`` — which raises InvalidURL before any network I/O.

Two measured incidents made this a shared module rather than a fetcher
private:

  1. the fetcher swallowed the exception into "status 0, empty content, no
     error", so a full A/B run returned 60/60 empty results with every gate
     green;
  2. crawl4ai's backend builds its own client and hit the same InvalidURL, so
     the test could not construct a backend at all.

The failure is environmental, so the guard has to be reachable from every
place that builds a client.

Call :func:`sanitize_no_proxy` immediately before constructing an
``httpx.AsyncClient`` (httpx reads the variables at construction time).
"""

from __future__ import annotations

import ipaddress
import logging
import os

import httpx

logger = logging.getLogger(__name__)


def sanitize_no_proxy() -> None:
    """Drop NO_PROXY entries httpx cannot turn into a mount pattern.

    httpx (<0.29) converts each NO_PROXY entry into an ``all://...`` mount
    key. A bracketed IPv6 literal ("[::1]" - a common default on developer
    machines) fails its ``is_ipv6_hostname`` check (ipaddress rejects the
    brackets), falls through to the wildcard branch, and the resulting key
    ``all://*[::1]`` raises ``InvalidURL: Invalid port ':1]'`` when the
    AsyncClient builds its mount table - before any network I/O. Every fetch
    then dies as a silent empty response (status 0, no error), which no
    downstream layer can explain. Observed 2026-11-13: a full A/B run
    returned 60/60 empty results with every gate green.

    httpx reads NO_PROXY through ``urllib.request.getproxies`` at client
    construction, so the fix must rewrite the env vars in place before the
    AsyncClient is built: drop the entries httpx cannot parse (bracketed
    IPv6; the unbracketed "::1" form works and is kept), keep the rest, and
    log the substitution once.
    """
    for var in ("NO_PROXY", "no_proxy"):
        raw = os.environ.get(var)
        if not raw:
            continue
        entries = [e.strip() for e in raw.split(",") if e.strip()]
        kept: list[str] = []
        dropped: list[str] = []
        for entry in entries:
            probe = entry[1:-1] if entry.startswith("[") and entry.endswith("]") else entry
            # Mirror httpx's mount-key construction exactly:
            #   is_ipv6_hostname(entry) -> all://[<entry>]     (works)
            #   is_ipv4_hostname(entry) -> all://<entry>       (works)
            #   otherwise               -> all://*<entry>      (crashes if
            #     the wildcard form contains a colon, which is exactly the
            #     bracketed-IPv6 case: "[::1]" fails the ipaddress check
            #     because of the brackets, then "all://*[::1]" dies on URL())
            if _is_ipv6_entry(entry):
                probe_key = f"http://[{probe}]"
            elif _is_ipv4_entry(entry):
                probe_key = f"http://{probe}"
            else:
                probe_key = f"http://*{entry}"
            try:
                httpx.URL(probe_key)
                kept.append(entry)
            except Exception:
                dropped.append(entry)
        if dropped:
            os.environ[var] = ",".join(kept)
            logger.warning(
                "NO_PROXY entries %r cannot be parsed by httpx <0.29 (bracketed "
                "IPv6 literals build an invalid mount pattern); dropped them "
                "from %s, kept %r",
                dropped,
                var,
                kept,
            )


def _is_ipv6_entry(entry: str) -> bool:
    """Mirror httpx's is_ipv6_hostname (which rejects bracketed forms)."""

    try:
        ipaddress.IPv6Address(entry.split("/")[0])
        return True
    except Exception:
        return False


def _is_ipv4_entry(entry: str) -> bool:
    """Mirror httpx's is_ipv4_hostname."""

    try:
        ipaddress.IPv4Address(entry.split("/")[0])
        return True
    except Exception:
        return False
