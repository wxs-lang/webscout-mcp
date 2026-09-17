"""Normalization layer: turn provider-specific results into WebResult.

This is the single place where a SearchResult (from any search provider)
or a FetchResponse (from fast-http or Crawl4AI) becomes a WebResult.
Adding a new provider only requires producing the existing
SearchResponse/FetchResponse shape — the normalization layer does the
rest.

This module never talks to the network, never raises into the caller on
malformed input, and never touches the SSRF guard.
"""

from __future__ import annotations

from typing import Any

from .fetch_provider import FetchResponse
from .logging_config import get_logger
from .search_provider import SearchResponse, SearchStatus
from .web_result import (
    BACKEND_CRAWL4AI,
    BACKEND_FAST_HTTP,
    BACKEND_SEARCH,
    WebResult,
    WebResultStatus,
)

log = get_logger(__name__)


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:  # noqa: BLE001
        return ""


def search_response_to_web_results(response: SearchResponse) -> list[WebResult]:
    """Normalize a SearchResponse into a list of WebResult.

    Never raises. Malformed provider results are skipped rather than
    crashing the search pipeline.
    """
    out: list[WebResult] = []
    for r in response.results:
        try:
            url = _safe_str(getattr(r, "url", ""))
            if not url:
                continue
            backend = _safe_str(getattr(r, "backend", "")) or response.provider
            out.append(
                WebResult(
                    url=url,
                    title=_safe_str(getattr(r, "title", "")),
                    content=_safe_str(getattr(r, "snippet", "")),
                    source=response.provider,
                    backend=backend or BACKEND_SEARCH,
                    content_type="text/plain",
                    published_at=None,  # search snippets rarely carry a reliable date
                    status=WebResultStatus.SUCCESS,
                    metadata={
                        "position": getattr(r, "position", 0),
                        "relevance_score": float(getattr(r, "relevance_score", 0.0) or 0.0),
                        "kind": "search_hit",
                    },
                )
            )
        except Exception:  # noqa: BLE001
            log.exception("failed to normalize search result; skipping")
            continue

    if response.status is SearchStatus.ERROR and not out:
        out.append(
            WebResult(
                url="",
                title="",
                content="",
                source=response.provider,
                backend=BACKEND_SEARCH,
                status=WebResultStatus.FAILED,
                metadata={
                    "error_code": response.error_type.value if response.error_type else None,
                    "error_message": response.error_message,
                },
            )
        )
    return out


def fetch_response_to_web_result(response: FetchResponse) -> WebResult:
    """Normalize a FetchResponse into a single WebResult.

    Classifies success / partial / failed deterministically:
      * HTTP < 400 and non-empty content      -> SUCCESS
      * HTTP < 400 but empty / very short     -> PARTIAL
      * HTTP >= 400 or error set              -> FAILED
    """
    backend = _classify_backend(response.provider)
    if response.is_success and response.content:
        status = WebResultStatus.SUCCESS
    elif response.is_success and not response.content:
        status = WebResultStatus.PARTIAL
    else:
        status = WebResultStatus.FAILED

    metadata: dict[str, Any] = {
        "status_code": response.status_code,
        "latency_ms": round(response.latency_ms, 2),
        "cached": response.cached,
        "extracted": response.extracted,
        "truncated": bool(response.metadata.get("truncated", False)),
        "extraction_failed": bool(response.error),
        "kind": "fetch",
    }
    # Carry through only scalar metadata from the backend (no PII / cookies).
    for k, v in (response.metadata or {}).items():
        if isinstance(v, (str, int, float, bool)) and k not in metadata:
            metadata[k] = v

    return WebResult(
        url=response.final_url or response.url,
        title=response.title or "",
        content=response.content or "",
        source=response.provider,
        backend=backend,
        content_type=response.content_type or "",
        published_at=None,  # only populated when a reliable date is known
        status=status,
        metadata=metadata,
    )


def _classify_backend(provider: str) -> str:
    p = (provider or "").lower()
    if "crawl" in p or "browser" in p:
        return BACKEND_CRAWL4AI
    if p in ("http", "fast", "fast-http"):
        return BACKEND_FAST_HTTP
    return p or BACKEND_FAST_HTTP
