"""Phase 2.7C — Progressive Content Delivery / Continuation.

One real fetch produces a local full-content snapshot; follow-up windows
(start_char > 0) are sliced from that snapshot with no new HTTP, extraction,
browser, or Jev activity.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from webscout_mcp.cache import Cache
from webscout_mcp.config import Config
from webscout_mcp.fetch_provider import FetchRequest, FetchResponse
from webscout_mcp.fetch_service import FetchService
from webscout_mcp.fetcher import Fetcher, FetchResult
from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter


def _make_fetcher(tmp_path) -> Fetcher:
    cfg = Config(cache_dir=tmp_path)
    cache = Cache(db_path=tmp_path / "cache.db", ttl=3600, max_size_mb=10)
    return Fetcher(cfg, cache)


def _install_body(fetcher: Fetcher, body: str, content_type: str = "text/plain", counter=None):
    async def _stub(url):
        if counter is not None:
            counter["n"] += 1
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            title="T",
            content=body,
            content_type=content_type,
        )

    fetcher._fetch_with_retry = _stub  # type: ignore[assignment]


def _fetch(fetcher, url, **kw):
    return asyncio.run(fetcher.fetch(url, **kw))


def test_first_window_metadata(tmp_path):
    f = _make_fetcher(tmp_path)
    _install_body(f, "A" * 20000)
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    assert r.content == "A" * 8000
    m = r.metadata
    assert m["content_start_char"] == 0
    assert m["content_end_char"] == 8000
    assert m["content_total_chars"] == 20000
    assert m["has_more"] is True
    assert m["next_start_char"] == 8000
    assert m["remaining_chars"] == 12000
    assert m["served_from_content_snapshot"] is False


def test_second_window_from_snapshot_no_network(tmp_path):
    f = _make_fetcher(tmp_path)
    calls = {"n": 0}
    _install_body(f, "A" * 20000, counter=calls)
    _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    assert calls["n"] == 1
    r2 = _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=8000)
    assert calls["n"] == 1  # no new HTTP fetch
    assert r2.content == "A" * 8000
    m = r2.metadata
    assert (m["content_start_char"], m["content_end_char"]) == (8000, 16000)
    assert m["served_from_content_snapshot"] is True
    assert m["next_start_char"] == 16000


def test_last_window(tmp_path):
    f = _make_fetcher(tmp_path)
    _install_body(f, "A" * 20000)
    _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=8000)
    r3 = _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=16000)
    assert r3.content == "A" * 4000
    m = r3.metadata
    assert (m["content_start_char"], m["content_end_char"]) == (16000, 20000)
    assert m["has_more"] is False
    assert m["next_start_char"] is None
    assert m["remaining_chars"] == 0


def test_windows_tile_full_content_without_gap_or_overlap(tmp_path):
    f = _make_fetcher(tmp_path)
    body = (("abcdefghij") * 2000)[:20000]  # 20000 deterministic chars
    _install_body(f, body)
    _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    pieces = []
    for start in (0, 8000, 16000):
        r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=start)
        pieces.append(r.content)
    assert "".join(pieces) == body  # exact, no marker / gap / overlap


def test_continuation_does_not_reextract(tmp_path):
    f = _make_fetcher(tmp_path)
    html = "<html><body><article>" + ("word " * 5000) + "</article></body></html>"
    _install_body(f, html, content_type="text/html")
    extract_calls = {"n": 0}
    orig = f._extract_content

    def counting(html_, fmt="markdown", **kw):
        extract_calls["n"] += 1
        return orig(html_, fmt, **kw)

    f._extract_content = counting  # type: ignore[assignment]
    _fetch(f, "https://example.com/p", extract=True, max_chars=8000)
    n_after_first = extract_calls["n"]
    assert n_after_first >= 1
    _fetch(f, "https://example.com/p", extract=True, max_chars=8000, start_char=8000)
    _fetch(f, "https://example.com/p", extract=True, max_chars=8000, start_char=16000)
    assert extract_calls["n"] == n_after_first  # no re-extraction on continuation


def test_snapshot_miss_rebuilds(tmp_path):
    f = _make_fetcher(tmp_path)
    calls = {"n": 0}
    _install_body(f, "A" * 20000, counter=calls)
    # No prior fetch -> no snapshot -> continuation triggers a real rebuild.
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=8000)
    assert calls["n"] == 1
    assert r.metadata["snapshot_rebuilt"] is True
    assert r.metadata["served_from_content_snapshot"] is False
    assert r.metadata["content_start_char"] == 8000


def test_bypass_cache_forces_refetch(tmp_path):
    f = _make_fetcher(tmp_path)
    calls = {"n": 0}
    _install_body(f, "A" * 20000, counter=calls)
    _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=8000, bypass_cache=True)
    assert calls["n"] == 2  # snapshot ignored
    assert r.metadata["served_from_content_snapshot"] is False


def test_snapshot_isolated_per_url(tmp_path):
    f = _make_fetcher(tmp_path)
    _install_body(f, "A" * 20000)
    _fetch(f, "https://a.example.com/p", extract=False, max_chars=8000)
    _install_body(f, "B" * 20000)
    # Continuation for a DIFFERENT url must not read A's snapshot.
    r = _fetch(f, "https://b.example.com/p", extract=False, max_chars=8000, start_char=8000)
    assert "A" not in r.content
    assert r.metadata["snapshot_rebuilt"] is True


def test_snapshot_isolated_per_format(tmp_path):
    f = _make_fetcher(tmp_path)
    calls = {"n": 0}
    _install_body(f, "A" * 20000, counter=calls)
    _fetch(f, "https://example.com/p", extract=False, output_format="markdown", max_chars=8000)
    # A text-format continuation must not reuse the markdown snapshot.
    r = _fetch(
        f,
        "https://example.com/p",
        extract=False,
        output_format="text",
        max_chars=8000,
        start_char=8000,
    )
    assert r.metadata.get("served_from_content_snapshot") is not True


def test_different_window_size_uses_same_snapshot(tmp_path):
    f = _make_fetcher(tmp_path)
    calls = {"n": 0}
    _install_body(f, "A" * 20000, counter=calls)
    _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=16000, start_char=8000)
    assert calls["n"] == 1  # larger window still from snapshot
    assert (r.metadata["content_start_char"], r.metadata["content_end_char"]) == (8000, 20000)
    assert r.metadata["served_from_content_snapshot"] is True


def test_negative_start_char_clamped(tmp_path):
    f = _make_fetcher(tmp_path)
    _install_body(f, "A" * 20000)
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=-5)
    assert r.metadata["content_start_char"] == 0
    assert len(r.content) == 8000


def test_start_at_total_empty(tmp_path):
    f = _make_fetcher(tmp_path)
    _install_body(f, "A" * 20000)
    _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=20000)
    assert r.content == ""
    assert r.metadata["has_more"] is False
    assert r.metadata["range_exhausted"] is True


def test_start_beyond_total_no_crash_no_restart(tmp_path):
    f = _make_fetcher(tmp_path)
    _install_body(f, "A" * 20000)
    _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000, start_char=99999)
    assert r.content == ""
    assert r.metadata["has_more"] is False
    assert r.metadata["content_start_char"] == 99999  # does not reset to 0
    assert r.metadata["range_exhausted"] is True


def test_short_complete_page_no_continuation(tmp_path):
    f = _make_fetcher(tmp_path)
    _install_body(f, "short body")
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    assert r.metadata["has_more"] is False
    assert r.metadata["next_start_char"] is None
    assert r.metadata["remaining_chars"] == 0


def test_no_inline_truncate_marker(tmp_path):
    f = _make_fetcher(tmp_path)
    _install_body(f, "A" * 20000)
    r = _fetch(f, "https://example.com/p", extract=False, max_chars=8000)
    assert "truncated" not in r.content
    assert len(r.content) == 8000


# ---------------------------------------------------------------------
# FetchService: a snapshot-hit continuation must skip escalation/browser/Jev.
# ---------------------------------------------------------------------
def _snapshot_response() -> FetchResponse:
    return FetchResponse(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=200,
        provider="http",
        content="A" * 100,
        content_type="text/html",
        extracted=True,
        metadata={
            "served_from_content_snapshot": True,
            "content_total_chars": 20000,
            "content_start_char": 8000,
            "content_end_char": 8100,
            "has_more": True,
            "next_start_char": 8100,
            "remaining_chars": 11900,
        },
    )


def test_service_snapshot_hit_skips_browser_and_jev(monkeypatch):
    class _Http:
        name = "http"
        capabilities = {ProviderCapability.FETCH}

        def __init__(self):
            self.fetch = AsyncMock(return_value=_snapshot_response())

        def get_health(self):
            return None

    class _Browser:
        name = "crawl4ai"
        capabilities = {ProviderCapability.BROWSER}

        def __init__(self):
            self.fetch = AsyncMock()

        def get_health(self):
            return None

    http, browser = _Http(), _Browser()
    router = ProviderRouter(
        provider_names=["http", "crawl4ai"],
        cost_tiers={"http": ProviderCostTier.FREE, "crawl4ai": ProviderCostTier.FREE},
        capabilities={"http": {ProviderCapability.FETCH}, "crawl4ai": {ProviderCapability.BROWSER}},
    )
    reg = ProviderRegistry(router=router)
    reg.register(http, capabilities={ProviderCapability.FETCH})
    reg.register(browser, capabilities={ProviderCapability.BROWSER})

    import webscout_mcp.fetch_service as fs

    monkeypatch.setattr(fs, "_JEV_AVAILABLE", True)
    svc = FetchService(reg)

    class _NoJev:
        name = "typesafe"

    svc._jev_client = _NoJev()
    jev_calls = {"n": 0}

    async def _fake_jev(*a, **k):
        jev_calls["n"] += 1

    monkeypatch.setattr(fs.jev_shadow, "maybe_record_fetch", _fake_jev, raising=False)

    route = asyncio.run(svc.fetch(FetchRequest(url="https://example.com/a", start_char=8000)))
    assert browser.fetch.await_count == 0
    assert jev_calls["n"] == 0
    assert route.browser_attempted is False
    assert route.escalation_decision is None
    out = route.legacy_out(max_chars=8000)
    assert out["continuation"]["served_from_snapshot"] is True
    assert out["continuation"]["start_char"] == 8000


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
