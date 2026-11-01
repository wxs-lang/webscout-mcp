"""The decompression bug: httpx must not be told Accept-Encoding by hand.

httpx disables automatic decompression when Accept-Encoding is set manually. The
browser fingerprint supplied one, so a gzip body was decoded as text:

    plain httpx : 577 chars, readable ratio 1.000
    Fetcher     : 311 chars, readable ratio 0.412, 145 U+FFFD

That defect is present from the initial commit (2026-08-28), which means every
gzip-compressed page served through this client has been mojibake, and the
content-usability SLO was counting that mojibake as content.

These tests pin the fix at the point where it can regress: the headers handed to
httpx.
"""

from __future__ import annotations

import asyncio
import gzip
import tempfile
from pathlib import Path

import httpx
import pytest

from webscout_mcp.core.cache import Cache
from webscout_mcp.core.config import Config
from webscout_mcp.fetcher import Fetcher


def _fetcher(tmp_path: Path) -> Fetcher:
    cfg = Config.from_env()
    return Fetcher(cfg, Cache(db_path=tmp_path / "c.db", ttl=60, max_size_mb=4))


# --- The client must let httpx negotiate encoding ----------------------


def test_fingerprint_does_not_supply_accept_encoding():
    """We must not hand httpx an encoding claim it may be unable to honour.

    The original bug: the fingerprint set `gzip, deflate, br` unconditionally. On a
    machine without the `brotli` package, servers obeyed and returned brotli that
    httpx could not decode, silently.

    Asserting on the client's final headers would be wrong - httpx legitimately adds
    `br` itself when brotli *is* installed. What we control, and what must stay
    clean, is the fingerprint.
    """
    from webscout_mcp.user_agent import UserAgentRotator

    headers = UserAgentRotator().get_fingerprint().to_headers()
    supplied = {name.lower() for name in headers}
    assert "accept-encoding" not in supplied, (
        "the fingerprint must leave encoding negotiation to httpx, which knows whether it can decode brotli"
    )


def test_client_still_sends_something_httpx_negotiated(tmp_path):
    """Removing our claim must not leave the client without any encoding support."""
    fetcher = _fetcher(tmp_path)

    async def build():
        return await fetcher._get_client()

    client = asyncio.run(build())
    encoding = client.headers.get("accept-encoding", "")
    assert encoding, "httpx should still negotiate gzip/deflate on its own"


def test_client_still_sends_a_browser_like_user_agent(tmp_path):
    """The fingerprint must survive the fix - it is what anti-bot checks read."""
    fetcher = _fetcher(tmp_path)

    async def build():
        return await fetcher._get_client()

    client = asyncio.run(build())
    assert client.headers.get("user-agent"), "a UA is still required"
    assert client.headers.get("accept"), "Accept is still required"


# --- A gzip body must arrive decoded ----------------------------------


def test_gzip_response_is_decompressed_by_the_client(tmp_path):
    """End to end through httpx's transport stack, no network needed."""
    payload = b"<html><body><p>" + b"real article text. " * 40 + b"</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8", "content-encoding": "gzip"},
            content=gzip.compress(payload),
        )

    fetcher = _fetcher(tmp_path)

    async def go():
        client = await fetcher._get_client()
        # Rebuild the client on a mock transport with the same headers.
        mock = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers=client.headers)
        try:
            response = await mock.get("https://example.test/")
            return response.text
        finally:
            await mock.aclose()

    text = asyncio.run(go())
    assert "real article text" in text, "gzip body must be decoded, not served as bytes"


def test_undecodable_encoding_leaves_the_body_unreadable(tmp_path):
    """The real failure mode: compressed bytes with an encoding httpx cannot decode.

    The body must be genuinely compressed; my first version sent plain text labelled
    with an unknown encoding, so "not decoded" and "already readable" were the same
    string and the assertion could not fail for the right reason.
    """
    from webscout_mcp.content_grading import readable_ratio

    payload = b"<html><body>" + b"real article text. " * 40 + b"</body></html>"
    compressed = gzip.compress(payload)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8", "content-encoding": "x-unknown"},
            content=compressed,
        )

    async def go():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            response = await client.get("https://example.test/")
            return response.text
        finally:
            await client.aclose()

    text = asyncio.run(go())
    assert "real article text" not in text, "compressed bytes must not surface as prose"
    assert readable_ratio(text) < 0.85, "and the grader must be able to see that"


# --- The grader catches it if it ever comes back ----------------------


def test_grader_flags_mojibake_as_garbled():
    """Defence in depth: even if decoding regresses, quality reporting notices."""
    from webscout_mcp.content_grading import assess

    mojibake = "\ufffd" * 200 + "Some text " + "\ufffd" * 150
    assert assess(mojibake).grade == "garbled"


def test_grader_accepts_genuinely_decoded_text():
    from webscout_mcp.content_grading import assess

    good = "This domain is for use in documentation examples. " * 10
    assert assess(good).usable
