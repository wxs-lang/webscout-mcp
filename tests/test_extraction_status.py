"""Extraction must say why it did not happen.

Measured before this change, in an environment whose extractor packages were
missing:

    status_code=200  extracted=false  error=null  content="<!doctype html>..."

The caller asked for markdown and received raw HTML with no explanation.
`extracted` was the only signal, and it cannot distinguish three very different
situations:

    unavailable  no extractor could be imported   (environment fault)
    empty        ran, but the page yielded too little text   (page fault)
    ok           text was produced

trafilatura and readability-lxml are declared core dependencies, so "unavailable"
should be rare - but when it happens the caller currently has no way to know, and
will happily feed raw HTML to a model that expects markdown.

These tests pin the distinction and the plumbing that carries it.
"""

from __future__ import annotations

import sys

import pytest

from webscout_mcp.fetcher import Fetcher, FetchResult

# --- The status vocabulary ---------------------------------------------


def test_extract_content_returns_a_status_tuple():
    """It used to return a bare string, so the reason was discarded."""
    result = Fetcher._extract_content("<html><body><p>hello world</p></body></html>", "markdown")
    assert isinstance(result, tuple) and len(result) == 2
    content, status = result
    assert isinstance(content, str)
    assert status in {"ok", "empty", "unavailable"}


def test_status_is_unavailable_when_no_extractor_is_importable(monkeypatch):
    """The environment fault the payload could not previously express.

    sys.modules[name] = None makes `import name` raise ImportError, so this
    exercises the real fall-through rather than only the availability probe.
    Patching the probe alone was not enough: with an extractor installed the
    function returns "ok" long before reaching the branch under test, so the
    first version of this test only proved anything on a machine that happened to
    lack the packages.
    """
    import webscout_mcp.fetcher as f

    for module in ("trafilatura", "readability", "html2text"):
        monkeypatch.setitem(sys.modules, module, None)
    monkeypatch.setattr(f, "_extractor_available", lambda: False)

    content, status = Fetcher._extract_content("<html><body><p>x</p></body></html>", "markdown")
    assert content == ""
    assert status == "unavailable"


def test_ok_status_accompanies_real_text():
    """When an extractor is present and the page has content, say ok."""
    import webscout_mcp.fetcher as f

    if not f._extractor_available():
        pytest.skip("no extractor installed in this environment")
    content, status = Fetcher._extract_content(
        "<html><body><article><p>" + ("meaningful sentence. " * 30) + "</p></article></body></html>",
        "markdown",
    )
    assert status == "ok"
    assert content.strip()


# --- The plumbing ------------------------------------------------------


def test_fetch_result_carries_the_status():
    r = FetchResult(url="u", final_url="u", status_code=200, extraction_status="unavailable")
    assert r.extraction_status == "unavailable"
    assert r.to_dict()["extraction_status"] == "unavailable"


def test_status_defaults_to_none_when_extraction_was_not_requested():
    r = FetchResult(url="u", final_url="u", status_code=200)
    assert r.extraction_status is None


def test_from_fetch_result_copies_the_status():
    """It was defined on both dataclasses and copied by neither."""
    from webscout_mcp.fetch_provider import FetchResponse

    r = FetchResult(url="u", final_url="u", status_code=200, content="x", extraction_status="empty")
    resp = FetchResponse.from_fetch_result(r, "http", 1.0)
    assert resp.extraction_status == "empty"


def test_legacy_out_surfaces_the_status():
    from webscout_mcp.fetch_provider import FetchResponse
    from webscout_mcp.fetch_service import FetchRouteResult, WebResult

    primary = FetchResponse(
        url="https://example.test/x",
        final_url="https://example.test/x",
        status_code=200,
        provider="http",
        content="<html>raw</html>",
        extracted=False,
        extraction_status="unavailable",
    )
    route = FetchRouteResult(
        primary_response=primary,
        final_response=primary,
        web_result=WebResult(url=primary.url),
    )
    out = route.legacy_out(max_chars=4000)
    assert out["extracted"] is False
    assert out["extraction_status"] == "unavailable"


# --- The payload stays additive ---------------------------------------


def test_payload_shape_is_additive_only():
    """COMPATIBILITY.md freezes the existing keys; this adds one."""
    from webscout_mcp.fetch_provider import FetchResponse
    from webscout_mcp.fetch_service import FetchRouteResult, WebResult

    primary = FetchResponse(
        url="https://example.test/ok",
        final_url="https://example.test/ok",
        status_code=200,
        provider="http",
        content="hello",
    )
    route = FetchRouteResult(
        primary_response=primary,
        final_response=primary,
        web_result=WebResult(url=primary.url),
    )
    out = route.legacy_out(max_chars=4000)
    for key in (
        "url",
        "final_url",
        "status_code",
        "title",
        "content",
        "content_type",
        "extracted",
        "cached",
        "error",
        "latency_ms",
        "error_code",
        "retryable",
    ):
        assert key in out, f"{key} disappeared"
    assert "extraction_status" in out


def test_availability_probe_is_cached_not_recomputed_per_fetch():
    """Importing three modules on every fetch would be wasteful; the probe is
    memoised, which is also why the tests monkeypatch it rather than uninstalling
    packages."""
    from webscout_mcp.fetcher import _extractor_available

    assert _extractor_available.cache_info().currsize <= 1
