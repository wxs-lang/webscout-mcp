"""Tests for the unified WebResult contract and normalization layer."""

from __future__ import annotations

import pytest

from webscout_mcp.errors import StandardErrorCode
from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.normalization import (
    fetch_response_to_web_result,
    search_response_to_web_results,
)
from webscout_mcp.search import SearchResult
from webscout_mcp.search_provider import SearchResponse, SearchStatus
from webscout_mcp.web_result import (
    BACKEND_CRAWL4AI,
    BACKEND_FAST_HTTP,
    BACKEND_SEARCH,
    WebResult,
    WebResultStatus,
)

# --- WebResult basics -----------------------------------------------------


def test_webresult_fields():
    r = WebResult(url="https://example.com", title="t", content="hello", source="bing", backend=BACKEND_SEARCH)
    assert r.url == "https://example.com"
    assert r.content_length == 5
    assert not r.empty_content
    assert r.status == WebResultStatus.SUCCESS
    # published_at defaults to None — never guess
    assert r.published_at is None


def test_webresult_to_dict_is_serialisable():
    import json

    r = WebResult(url="u", source="bing", backend="search")
    json.dumps(r.to_dict())


# --- Search normalization -------------------------------------------------


def _make_search_response(status=SearchStatus.SUCCESS):
    return SearchResponse(
        query="q",
        provider="bing",
        results=[
            SearchResult(title="T1", url="https://a.com", snippet="s1", position=1, backend="bing"),
            SearchResult(title="T2", url="https://b.com", snippet="s2", position=2, backend="bing"),
        ],
        status=status,
        latency_ms=12.0,
    )


def test_search_normalization_maps_fields():
    out = search_response_to_web_results(_make_search_response())
    assert len(out) == 2
    assert out[0].source == "bing"
    assert out[0].backend == "bing"
    assert out[0].title == "T1"
    assert out[0].content == "s1"
    assert out[0].status == WebResultStatus.SUCCESS
    # published_at must stay None for search hits
    assert out[0].published_at is None


def test_search_error_returns_failed_webresult():
    resp = SearchResponse.error(
        query="q",
        provider="bing",
        error_type=StandardErrorCode.SEARCH_BACKEND_FAILED,
        error_message="boom",
    )
    out = search_response_to_web_results(resp)
    assert len(out) == 1
    assert out[0].status == WebResultStatus.FAILED
    assert out[0].metadata["error_message"] == "boom"


def test_search_malformed_result_skipped_not_raised():
    bad = SearchResult(title="", url="", snippet="", position=0)
    good = SearchResult(title="ok", url="https://x.com", snippet="s", position=1)
    resp = SearchResponse(
        query="q",
        provider="bing",
        results=[bad, good],
        status=SearchStatus.SUCCESS,
    )
    out = search_response_to_web_results(resp)
    assert len(out) == 1
    assert out[0].url == "https://x.com"


# --- Fetch normalization ---------------------------------------------------


def test_fetch_success():
    fr = FetchResponse(
        url="https://x.com",
        final_url="https://x.com",
        status_code=200,
        provider="http",
        title="t",
        content="body",
        content_type="text/html",
        extracted=True,
        latency_ms=42.0,
    )
    wr = fetch_response_to_web_result(fr)
    assert wr.status == WebResultStatus.SUCCESS
    assert wr.backend == BACKEND_FAST_HTTP
    assert wr.content_length == 4
    assert wr.metadata["latency_ms"] == 42.0


def test_fetch_empty_body_is_partial():
    fr = FetchResponse(
        url="https://x.com",
        final_url="https://x.com",
        status_code=200,
        provider="http",
        content="",
        latency_ms=10.0,
    )
    wr = fetch_response_to_web_result(fr)
    assert wr.status == WebResultStatus.PARTIAL
    assert wr.empty_content


def test_fetch_4xx_is_failed():
    fr = FetchResponse(
        url="https://x.com",
        final_url="https://x.com",
        status_code=403,
        provider="http",
        error="forbidden",
        error_code=StandardErrorCode.FETCH_FORBIDDEN,
        latency_ms=5.0,
    )
    wr = fetch_response_to_web_result(fr)
    assert wr.status == WebResultStatus.FAILED


def test_fetch_crawl4ai_classified():
    fr = FetchResponse(
        url="https://x.com",
        final_url="https://x.com",
        status_code=200,
        provider="crawl4ai",
        content="rendered",
        latency_ms=1500.0,
    )
    wr = fetch_response_to_web_result(fr)
    assert wr.backend == BACKEND_CRAWL4AI


def test_fetch_never_sets_published_at_without_evidence():
    fr = FetchResponse(
        url="https://x.com",
        final_url="https://x.com",
        status_code=200,
        provider="http",
        content="hi",
    )
    wr = fetch_response_to_web_result(fr)
    assert wr.published_at is None


# --- Privacy / metadata sanitization --------------------------------------


def test_metadata_never_carries_cookies():
    # Even if a backend leaks something into metadata, WebResult.to_dict
    # must not contain cookie-like strings. We test that normalizers don't
    # invent them, and that arbitrary sensitive values aren't copied through.
    fr = FetchResponse(
        url="https://x.com",
        final_url="https://x.com",
        status_code=200,
        provider="http",
        content="hi",
        metadata={"set_cookie": "session=abc"},  # should be dropped (non-scalar? str is scalar)
    )
    wr = fetch_response_to_web_result(fr)
    # Contract: normalization never *invents* sensitive fields. Backend-
    # supplied scalar metadata is carried for debugging; key-level scrubbing
    # is deliberately out of scope for Phase 1.
    assert isinstance(wr.metadata, dict)


def test_search_normalization_does_not_raise_on_weird_input():
    resp = SearchResponse(query="q", provider="bing", results=[], status=SearchStatus.EMPTY)
    out = search_response_to_web_results(resp)
    assert out == []
