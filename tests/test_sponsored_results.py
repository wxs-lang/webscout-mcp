"""A paid placement must be distinguishable from an answer.

## Measured

Six queries, 48 results, 2 ads (4%):

    HP® Official Laptops - Shop 13, 15, & 17 Inch
    https://duckduckgo.com/y.js?ad_domain=hp.com&ad_provider=bingv7aa&ad_type=txad&click_metadata=...

    UC San Diego - Learn Python - Online Python Programming
    https://duckduckgo.com/y.js?ad_domain=ucsd.edu&...

Nothing in the payload separated them from the organic results beside them: the title reads like
an answer, `position` is an ordinary rank, and `backend` says `duckduckgo` exactly as the
organic hits do.

## Why 4% is still worth a field

The consumer is an agent. An ad presented as a result is a paid claim it may quote as a
finding, with no way to notice. Volume is not the measure here - attribution is.

## The signal

The redirect URL, not the title. An advertiser writes its own headline; the click still has to
route through the ad network to be billed, so the URL is what cannot be faked.

## Flagged, not filtered

Dropping the row would change the count a caller sees and would hide that the query triggered
advertising at all. The caller can act on a sponsored result; it cannot act on one it was never
told was sponsored.
"""

from __future__ import annotations

import pytest

from webscout_mcp.search import _is_sponsored


@pytest.mark.parametrize(
    "url",
    [
        "https://duckduckgo.com/y.js?ad_domain=hp.com&ad_provider=bingv7aa&ad_type=txad",
        "https://duckduckgo.com/y.js?ad_domain=ucsd.edu&click_metadata=CqicPM",
        "https://www.google.com/aclk?sa=L&ai=xyz",
        "https://www.googleadservices.com/pagead/aclk?x=1",
        "https://ad.doubleclick.net/ddm/trackclk/123",
        "https://www.bing.com/aclick?ld=e8",
    ],
)
def test_a_paid_placement_is_detected(url):
    assert _is_sponsored(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.python.org/3/library/asyncio.html",
        "https://realpython.com/async-io-python/",
        "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
        "https://en.wikipedia.org/wiki/Web_scraping",
        "https://github.com/python/cpython",
    ],
)
def test_an_ordinary_result_is_not_flagged(url):
    assert _is_sponsored(url) is False


def test_an_empty_url_is_not_flagged():
    """No URL means no claim about sponsorship."""
    assert _is_sponsored("") is False


def test_the_check_is_case_insensitive():
    assert _is_sponsored("https://DuckDuckGo.com/Y.JS?AD_DOMAIN=hp.com") is True


def test_a_url_merely_containing_ad_like_words_is_not_flagged():
    """`ad` appears in ordinary paths; only the specific redirect shapes count."""
    assert _is_sponsored("https://example.com/download/advertisement-policy") is False
    assert _is_sponsored("https://example.com/header/ads-are-bad") is False


def test_the_payload_carries_the_flag():
    """Source-level: the tool must actually emit it, not merely be able to compute it."""
    import inspect

    from webscout_mcp.server import create_server

    source = inspect.getsource(create_server)
    start = source.find("async def web_search")
    assert start != -1
    end = source.find("@mcp.tool", start + 1)
    body = source[start : end if end != -1 else len(source)]

    assert "_is_sponsored" in body, "web_search does not call the sponsorship check"
    assert '"sponsored"' in body, "the payload does not expose a sponsored field"
