"""Bing's redirect URLs must be resolved before a caller sees them.

## Measured

20 real results from `bing`, 5 of them (25%) were redirects:

    https://www.bing.com/ck/a?!&&p=bb4b...&u=a1aHR0cHM6...

The `href` starts with `http`, so `BingBackend`'s existing check accepted it - the code only
skipped `google.com`. A caller cannot use that URL: it is an expiring opaque token, not the
page.

After decoding, the same query returned the destinations:

    https://dev.to/alvisonhunter/asynchronous-python-a-beginners-guide-to-asyncio-2d5p
    https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html

## The format

`u=a1<base64url>`, payload decodes to the destination. Verified on six live results.

## What these tests pin

- a redirect resolves to its destination
- a direct link passes through untouched
- a malformed token returns the original href rather than raising or returning empty -
  dropping a result would silently change the count a caller sees
"""

from __future__ import annotations

import base64

import pytest

from webscout_mcp.search import _decode_bing_redirect


def _redirect(url: str) -> str:
    token = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&&p=abc123&u=a1{token}&ntb=1"


def test_a_redirect_resolves_to_its_destination():
    target = "https://dev.to/someone/asyncio-guide-2d5p"
    assert _decode_bing_redirect(_redirect(target)) == target


def test_the_known_sample_from_the_investigation():
    """`a1aHR0cHM6Ly9leGFtcGxlLmNvbQ` decodes to https://example.com."""
    assert (
        _decode_bing_redirect("https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbQ&ntb=1") == "https://example.com"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
        "https://www.w3schools.com/rust/rust_ownership.php",
        "https://example.com/path?q=1&b=2",
    ],
)
def test_a_direct_link_is_untouched(url):
    assert _decode_bing_redirect(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.bing.com/ck/a?u=not-a-valid-token&ntb=1",
        "https://www.bing.com/ck/a?u=&ntb=1",
        "https://www.bing.com/ck/a",
        "https://www.bing.com/ck/a?u=a1&ntb=1",
    ],
)
def test_a_malformed_token_returns_the_original(url):
    """An opaque link is better than a dropped result: dropping changes the count."""
    assert _decode_bing_redirect(url) == url


def test_decoding_does_not_reach_other_hosts():
    """Only bing's redirect form is handled; others pass through."""
    other = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com"
    assert _decode_bing_redirect(other) == other


def test_the_backend_actually_calls_the_decoder():
    """A correct helper that is never called fixes nothing.

    Source-level, because constructing a BingBackend needs a live HTTP client and the point
    under test is whether the call site uses the decoder at all.
    """
    import inspect

    from webscout_mcp.search import BingBackend

    source = inspect.getsource(BingBackend)
    assert "_decode_bing_redirect(" in source, (
        "BingBackend does not call the decoder; redirects will still reach the caller"
    )


def test_the_backend_does_not_assign_a_raw_href():
    """The previous form accepted any href starting with http, redirects included."""
    import inspect
    import re

    from webscout_mcp.search import BingBackend

    source = inspect.getsource(BingBackend)
    raw_assignments = re.findall(r"url\s*=\s*link\.get\(\s*[\"']href[\"']", source)
    assert not raw_assignments, (
        f"raw href assignment still present: {raw_assignments}; "
        "it accepts bing.com/ck/a tokens as if they were destinations"
    )
