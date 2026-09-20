"""Phase 2.7A — Content Sufficiency & Truncation Semantics.

Distinguishes "HTTP did not fetch enough" from "WebScout truncated a
complete response", fixes cache-key semantics across different output
limits, and ensures truncation is a delivery signal (not a browser
escalation trigger).
"""

from __future__ import annotations

import asyncio

import pytest

from webscout_mcp.cache import Cache
from webscout_mcp.config import Config
from webscout_mcp.fetch_escalation import should_escalate_to_browser
from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.fetcher import Fetcher, FetchResult
from webscout_mcp.normalization import fetch_response_to_web_result
from webscout_mcp.web_result import WebResultStatus


def _make_fetcher(tmp_path) -> Fetcher:
    cfg = Config(cache_dir=tmp_path)
    cache = Cache(db_path=tmp_path / "cache.db", ttl=3600, max_size_mb=10)
    return Fetcher(cfg, cache)


def _stub_result(html: str, content_type: str = "text/html; charset=utf-8") -> FetchResult:
    return FetchResult(
        url="https://example.com/page",
        final_url="https://example.com/page",
        status_code=200,
        title="Page",
        content=html,
        content_type=content_type,
    )


def _install_stub(fetcher: Fetcher, html: str, content_type: str = "text/plain") -> None:
    async def _stub(url):
        # Fresh object per call, mirroring a real network fetch (the
        # fetcher mutates content in place during truncation).
        return _stub_result(html, content_type=content_type)

    fetcher._fetch_with_retry = _stub  # type: ignore[assignment]


def test_truncation_metadata_when_over_limit(tmp_path):
    """pre-limit 12000, max_chars=8000 -> truncated with correct scalars."""
    fetcher = _make_fetcher(tmp_path)
    # Plain text so extraction is a no-op and lengths are deterministic.
    body = "A" * 12000
    _install_stub(fetcher, body, content_type="text/plain")

    result = asyncio.run(fetcher.fetch("https://example.com/page", max_chars=8000, bypass_cache=True))

    meta = result.metadata
    assert meta["truncated_by_output_limit"] is True
    assert meta["truncated"] is True
    assert meta["output_limit_chars"] == 8000
    assert meta["pre_limit_content_chars"] == 12000
    assert meta["omitted_chars"] == 4000
    assert meta["returned_content_chars"] == len(result.content)
    assert meta["source_content_chars"] == 12000
    assert result.content.startswith("A" * 8000)
    # Phase 2.7C: the inline truncate marker is replaced by structured
    # continuation metadata; the window is an exact slice (8000 chars).
    assert len(result.content) == 8000
    assert meta["has_more"] is True
    assert meta["next_start_char"] == 8000
    assert meta["content_total_chars"] == 12000
    assert meta["remaining_chars"] == 4000
    assert meta["content_start_char"] == 0 and meta["content_end_char"] == 8000


def test_no_truncation_when_under_limit(tmp_path):
    fetcher = _make_fetcher(tmp_path)
    body = "B" * 5000
    _install_stub(fetcher, body, content_type="text/plain")

    result = asyncio.run(fetcher.fetch("https://example.com/page", max_chars=8000, bypass_cache=True))

    meta = result.metadata
    assert meta["truncated_by_output_limit"] is False
    assert meta["omitted_chars"] == 0
    assert meta["pre_limit_content_chars"] == 5000
    assert meta["returned_content_chars"] == 5000
    assert len(result.content) == 5000


def test_none_max_chars_defaults_to_8000(tmp_path):
    fetcher = _make_fetcher(tmp_path)
    body = "C" * 9000
    _install_stub(fetcher, body, content_type="text/plain")

    result = asyncio.run(fetcher.fetch("https://example.com/page", max_chars=None, bypass_cache=True))

    assert result.metadata["output_limit_chars"] == 8000
    assert result.metadata["truncated_by_output_limit"] is True


def test_none_and_8000_share_cache_entry(tmp_path):
    """max_chars=None and max_chars=8000 are the same effective limit."""
    fetcher = _make_fetcher(tmp_path)
    body = "D" * 9000
    _install_stub(fetcher, body, content_type="text/plain")

    first = asyncio.run(fetcher.fetch("https://example.com/page", max_chars=None))
    stub_calls = {"n": 0}

    async def _stub(url):
        stub_calls["n"] += 1
        return _stub_result(body, content_type="text/plain")

    fetcher._fetch_with_retry = _stub  # type: ignore[assignment]
    second = asyncio.run(fetcher.fetch("https://example.com/page", max_chars=8000))

    assert first.cached is False
    assert second.cached is True
    assert stub_calls["n"] == 0  # served from cache


def test_different_limits_do_not_share_cache(tmp_path):
    """8000 and 200000 must not collide on the same cache entry."""
    fetcher = _make_fetcher(tmp_path)
    body = "E" * 50000
    _install_stub(fetcher, body, content_type="text/plain")

    small = asyncio.run(fetcher.fetch("https://example.com/page", max_chars=8000))
    assert small.metadata["truncated_by_output_limit"] is True

    large = asyncio.run(fetcher.fetch("https://example.com/page", max_chars=200000))
    # The second request must not be served the truncated 8000 entry.
    assert large.cached is False
    assert large.metadata["truncated_by_output_limit"] is False
    assert len(large.content) == 50000


def test_cached_8000_does_not_pollute_200000(tmp_path):
    """Pre-cache 8000 first; a later 200000 request must re-fetch fully."""
    fetcher = _make_fetcher(tmp_path)
    body = "F" * 30000
    calls = {"n": 0}

    async def _stub(url):
        calls["n"] += 1
        return _stub_result(body, content_type="text/plain")

    fetcher._fetch_with_retry = _stub  # type: ignore[assignment]

    asyncio.run(fetcher.fetch("https://example.com/page", max_chars=8000))
    big = asyncio.run(fetcher.fetch("https://example.com/page", max_chars=200000))

    assert calls["n"] == 2  # two distinct network fetches
    assert len(big.content) == 30000
    assert big.metadata["omitted_chars"] == 0


def test_webresult_truncated_reflects_flag():
    resp = FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        provider="http",
        content="x" * 8000 + "\n... [truncated]",
        metadata={
            "truncated_by_output_limit": True,
            "pre_limit_content_chars": 20000,
            "output_limit_chars": 8000,
            "omitted_chars": 12000,
        },
    )
    wr = fetch_response_to_web_result(resp)
    assert wr.truncated is True
    assert wr.metadata["truncated"] is True
    assert wr.metadata["pre_limit_content_chars"] == 20000


def test_truncated_webresult_is_partial():
    resp = FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        provider="http",
        content="y" * 8000,
        metadata={"truncated_by_output_limit": True},
    )
    wr = fetch_response_to_web_result(resp)
    assert wr.status == WebResultStatus.PARTIAL


def test_complete_webresult_is_success():
    resp = FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        provider="http",
        content="complete page body",
        metadata={"truncated_by_output_limit": False},
    )
    wr = fetch_response_to_web_result(resp)
    assert wr.status == WebResultStatus.SUCCESS


def test_output_truncation_does_not_trigger_browser():
    """A page truncated only by the output budget must not escalate."""
    resp = FetchResponse(
        url="https://example.com/doc",
        final_url="https://example.com/doc",
        status_code=200,
        provider="http",
        content="z" * 8000,
        raw_html="<html><body><article>" + "z" * 40000 + "</article></body></html>",
        metadata={
            "truncated_by_output_limit": True,
            "pre_limit_content_chars": 40000,
            "omitted_chars": 32000,
        },
    )
    decision = should_escalate_to_browser(resp)
    assert decision.escalate is False
    assert decision.details.get("truncated_by_output_limit") is True


def test_challenge_still_escalates_with_raw_html():
    """Regression: soft-block detection uses internal raw_html."""
    challenge = (
        "<html><head><title>Just a moment...</title></head>"
        "<body><script>window._cf_chl_opt={};</script>"
        "<div id='cf-challenge'>Checking your browser</div></body></html>"
    )
    resp = FetchResponse(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        provider="http",
        content="Checking your browser",
        raw_html=challenge,
        metadata={},
    )
    decision = should_escalate_to_browser(resp)
    assert decision.escalate is True


def test_metadata_never_carries_raw_html():
    result = FetchResult(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        content="short",
        content_type="text/html",
        raw_html="<html>secret markup</html>",
    )
    resp = FetchResponse.from_fetch_result(result, provider="http", latency_ms=1.0)
    dumped = resp.to_dict()
    assert "raw_html" not in dumped
    assert "raw_html" not in resp.metadata
    wr = fetch_response_to_web_result(resp)
    assert "raw_html" not in wr.metadata
    assert wr.to_dict().get("metadata", {}).get("raw_html") is None


def test_mcp_tool_count_unchanged():
    """Guard: Phase 2.7A must not add MCP tools."""
    import subprocess
    import sys
    from pathlib import Path

    server = Path(__file__).resolve().parents[1] / "webscout_mcp" / "server.py"
    out = subprocess.run(
        [sys.executable, "-c", f"print(open(r'{server}').read().count('@mcp.tool'))"],
        capture_output=True,
        text=True,
    )
    assert int(out.stdout.strip()) == 11


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
