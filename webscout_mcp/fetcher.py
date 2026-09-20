"""Smart web fetcher with retry, caching, rate-limiting, and content extraction.

This is the workhorse of webscout-mcp. It fetches a URL, optionally extracts
the main article content (via trafilatura + readability-lxml fallback), and
returns structured data. All network calls go through the rate limiter and cache.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import httpx

from .cache import Cache
from .config import Config
from .user_agent import UserAgentRotator
from .utils import TokenBucket, normalize_url

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    """Result of a fetch operation."""

    url: str
    final_url: str
    status_code: int
    title: str = ""
    content: str = ""
    content_type: str = ""
    extracted: bool = False
    cached: bool = False
    error: str | None = None
    raw_html: str = ""
    metadata: dict = field(default_factory=dict)
    response_time: float = 0.0  # Response time in seconds
    retries: int = 0  # Number of retries

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "title": self.title,
            "content": self.content,
            "content_type": self.content_type,
            "extracted": self.extracted,
            "cached": self.cached,
            "error": self.error,
            "metadata": self.metadata,
            "response_time": self.response_time,
            "retries": self.retries,
        }


class Fetcher:
    """Async web fetcher with intelligent defaults.

    Enhanced features:
    - Cookie management (persistent CookieJar across requests)
    - Complete browser fingerprint headers (Sec-Fetch-*, Connection, Cache-Control)
    - Connection pool optimization
    - Smart content type detection
    """

    def __init__(self, config: Config, cache: Cache | None = None):
        self.config = config
        self.cache = cache
        self.rate_limiter = TokenBucket(
            rate=config.rate_limit_per_second,
            burst=config.rate_limit_burst,
        )
        self._client: httpx.AsyncClient | None = None
        self._cookies: httpx.Cookies = httpx.Cookies()
        self._ua_rotator = UserAgentRotator(persistent=True)
        # Request statistics
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "cache_hits": 0,
            "total_response_time": 0.0,
            "total_retries": 0,
            "status_codes": {},
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # Use complete browser fingerprint headers
            fingerprint = self._ua_rotator.get_fingerprint()
            headers = fingerprint.to_headers()
            # Override User-Agent with config value if set
            if self.config.user_agent:
                headers["User-Agent"] = self.config.user_agent

            client_kwargs: dict = {
                "timeout": httpx.Timeout(self.config.request_timeout),
                "follow_redirects": True,
                "headers": headers,
                "max_redirects": 5,
                "cookies": self._cookies,
                "limits": httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=20,
                    keepalive_expiry=30.0,
                ),
            }
            proxies: dict[str, str] = {}
            if self.config.proxy_http:
                proxies["http://"] = self.config.proxy_http
            if self.config.proxy_https:
                proxies["https://"] = self.config.proxy_https
            if proxies:
                client_kwargs["proxies"] = proxies
            self._client = httpx.AsyncClient(**client_kwargs)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def get_stats(self) -> dict:
        """Get request statistics.

        Returns:
            Dictionary with total_requests, successful_requests, failed_requests,
            cache_hits, average_response_time, total_retries, and status_codes.
        """
        stats = dict(self._stats)
        if stats["total_requests"] > 0:
            stats["average_response_time"] = round(stats["total_response_time"] / stats["total_requests"], 4)
        else:
            stats["average_response_time"] = 0.0
        stats["success_rate"] = (
            round(stats["successful_requests"] / stats["total_requests"], 4) if stats["total_requests"] > 0 else 0.0
        )
        return stats

    def reset_stats(self) -> None:
        """Reset request statistics."""
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "cache_hits": 0,
            "total_response_time": 0.0,
            "total_retries": 0,
            "status_codes": {},
        }

    async def fetch(
        self,
        url: str,
        extract: bool = True,
        output_format: str | None = None,
        max_chars: int | None = None,
        bypass_cache: bool = False,
        start_char: int = 0,
    ) -> FetchResult:
        url = normalize_url(url)
        fmt = output_format or self.config.extract_output_format
        # The output limit is the per-window target size (Phase 2.7C): it is
        # the maximum chars returned in ONE response, not a cap on how much
        # of the page is fetched/extracted.
        effective_limit = max_chars or 8000
        # Negative offsets are not meaningful; clamp deterministically to 0.
        if not isinstance(start_char, int) or start_char < 0:
            start_char = 0
        # The content snapshot holds the FULL extracted article; its identity
        # is independent of window size / offset so one snapshot serves every
        # continuation window. The Cache hashes this key (SHA-256), so the
        # full URL is never stored verbatim in SQLite.
        snapshot_key = f"snapshot:{url}:{extract}:{fmt}"
        # The per-window response cache additionally varies by limit+offset.
        cache_key = f"fetch:{url}:{extract}:{fmt}:{effective_limit}:{start_char}"

        # Continuation fast path: serve the next window from the local
        # snapshot. No HTTP, no extraction, no browser, no Jev.
        if start_char > 0 and not bypass_cache and self.cache:
            snap = self._load_snapshot(snapshot_key)
            if snap is not None:
                return self._window_from_snapshot(snap, effective_limit, start_char, cache_layer_hit=True)
            # Snapshot missing/expired: fall through to a real fetch and
            # rebuild it, flagging the rebuild so callers never assume a hit.
            snapshot_rebuilt = True
        else:
            snapshot_rebuilt = False

        if not bypass_cache and self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                import json

                data = json.loads(cached["value"])
                result = FetchResult(**data)
                result.cached = True
                self._stats["cache_hits"] += 1
                return result

        await self.rate_limiter.acquire(url)
        import time

        start_time = time.monotonic()
        result = await self._fetch_with_retry(url)
        result.response_time = time.monotonic() - start_time

        # Update statistics
        self._stats["total_requests"] += 1
        self._stats["total_response_time"] += result.response_time
        self._stats["total_retries"] += result.retries
        status_code = str(result.status_code)
        self._stats["status_codes"][status_code] = self._stats["status_codes"].get(status_code, 0) + 1

        if result.error is None:
            self._stats["successful_requests"] += 1
        else:
            self._stats["failed_requests"] += 1

        if result.error is None and result.content:
            # Length of the decoded HTTP body before extraction (for HTML
            # pages this is raw HTML char count). Scalar diagnostic only —
            # the raw body itself is never propagated as metadata.
            source_content_chars = len(result.content)
            if self._is_extractable(result.content_type):
                result.raw_html = result.content
            if extract and self._is_extractable(result.content_type):
                extracted = await asyncio.to_thread(self._extract_content, result.content, fmt)
                if extracted:
                    result.content = extracted
                    result.extracted = True
            # FULL extracted article, captured BEFORE any windowing. This is
            # what the continuation snapshot preserves.
            full_content = result.content

            # Persist the full-content snapshot (allowlisted scalars only —
            # never headers/cookies/tokens). Reuses the existing Cache TTL and
            # size pruning; it is a cache, not a permanent content store.
            if self.cache and result.status_code < 400:
                self._store_snapshot(
                    snapshot_key,
                    {
                        "url": result.url,
                        "final_url": result.final_url,
                        "status_code": result.status_code,
                        "title": result.title,
                        "content": full_content,
                        "content_type": result.content_type,
                        "extracted": result.extracted,
                    },
                )

            result = self._apply_window(result, full_content, effective_limit, start_char)
            result.metadata["served_from_content_snapshot"] = False
            result.metadata["snapshot_rebuilt"] = snapshot_rebuilt
            result.metadata["source_content_chars"] = source_content_chars

        if self.cache and result.error is None and result.status_code < 400 and start_char == 0:
            import json

            self.cache.set(
                cache_key,
                json.dumps(result.to_dict()),
                content_type="application/json",
            )
        return result

    # ------------------------------------------------------------------
    # Progressive content delivery (Phase 2.7C)
    # ------------------------------------------------------------------
    def _load_snapshot(self, snapshot_key: str) -> dict | None:
        if not self.cache:
            return None
        import json

        try:
            entry = self.cache.get(snapshot_key)
            if not entry:
                return None
            return json.loads(entry["value"])
        except Exception:
            return None

    def _store_snapshot(self, snapshot_key: str, snap: dict) -> None:
        import json

        try:
            self.cache.set(snapshot_key, json.dumps(snap), content_type="application/json")
        except Exception:
            # Snapshot persistence must never break content delivery.
            logger.debug("content snapshot store failed", exc_info=True)

    @staticmethod
    def _window_metadata(total: int, start: int, end: int, limit: int) -> dict:
        """Deterministic [start, end) window scalars (offsets into the FULL
        extracted article, never into a marker-suffixed returned string)."""
        has_more = end < total
        remaining = max(total - end, 0)
        range_exhausted = start >= total
        return {
            "content_start_char": start,
            "content_end_char": end,
            "content_total_chars": total,
            "has_more": has_more,
            "next_start_char": end if has_more else None,
            "remaining_chars": remaining,
            # Phase 2.7A-compatible truncation semantics, now window-aware:
            # "truncated" means "more content follows this window".
            "output_limit_chars": limit,
            "pre_limit_content_chars": total,
            "returned_content_chars": end - start,
            "truncated_by_output_limit": has_more,
            "omitted_chars": remaining,
            "truncated": has_more,
            "range_exhausted": range_exhausted,
        }

    def _apply_window(self, result: FetchResult, full_content: str, limit: int, start: int) -> FetchResult:
        total = len(full_content)
        if start >= total:
            # At/past EOF: stable empty window, never restart at 0.
            window = ""
            end = start
        else:
            window = full_content[start : start + limit]
            end = start + len(window)
        result.content = window  # exact slice; no artificial truncate marker
        meta = self._window_metadata(total, start, end, limit)
        result.metadata.update(meta)
        return result

    def _window_from_snapshot(self, snap: dict, limit: int, start: int, cache_layer_hit: bool) -> FetchResult:
        full_content = snap.get("content", "") or ""
        result = FetchResult(
            url=snap.get("url", ""),
            final_url=snap.get("final_url", "") or snap.get("url", ""),
            status_code=int(snap.get("status_code", 200) or 200),
            title=snap.get("title", ""),
            content="",
            content_type=snap.get("content_type", ""),
            extracted=bool(snap.get("extracted", False)),
            cached=True,
        )
        result = self._apply_window(result, full_content, limit, start)
        result.metadata["served_from_content_snapshot"] = True
        result.metadata["snapshot_rebuilt"] = False
        result.metadata["source_content_chars"] = len(full_content)
        self._stats["cache_hits"] += 1
        return result

    async def _fetch_with_retry(self, url: str) -> FetchResult:
        """Fetch with exponential backoff retry.

        Retries on all httpx errors (Timeout, ConnectError, PoolTimeout, etc.),
        asyncio.TimeoutError, and HTTP 5xx status codes. Does not retry on 4xx.
        """
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                client = await self._get_client()
                response = await client.get(url)

                if response.status_code >= 500 and attempt < self.config.max_retries - 1:
                    last_error = Exception(f"HTTP {response.status_code}")
                    await asyncio.sleep(self.config.retry_backoff * (2**attempt))
                    continue

                content_length = int(response.headers.get("content-length", 0))
                if content_length > self.config.max_content_length:
                    return FetchResult(
                        url=url,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type", ""),
                        error=f"Content too large: {content_length} bytes (limit {self.config.max_content_length})",
                    )

                text = response.text
                title = self._extract_title(text)
                return FetchResult(
                    url=url,
                    final_url=str(response.url),
                    status_code=response.status_code,
                    title=title,
                    content=text,
                    content_type=response.headers.get("content-type", ""),
                    metadata={
                        "encoding": response.encoding,
                        "headers": dict(response.headers),
                    },
                )
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_backoff * (2**attempt))
            except Exception as exc:
                return FetchResult(
                    url=url,
                    final_url=url,
                    status_code=0,
                    error=f"{type(exc).__name__}: {exc}",
                )

        return FetchResult(
            url=url,
            final_url=url,
            status_code=0,
            error=f"Failed after {self.config.max_retries} retries: {last_error}",
        )

    @staticmethod
    def _is_extractable(content_type: str) -> bool:
        if not content_type:
            return False
        ct = content_type.lower()
        return any(marker in ct for marker in ("html", "xml", "xhtml", "text/plain", "text/html"))

    @staticmethod
    def _extract_title(html: str) -> str:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            if soup.title and soup.title.string:
                return soup.title.string.strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_content(
        html: str,
        output_format: str = "markdown",
        include_images: bool = False,
        include_videos: bool = False,
    ) -> str:
        """Extract main article content.

        Uses multiple extractors in order:
        1. trafilatura (primary, best quality)
        2. readability-lxml (fallback)
        3. html2text (final fallback, if available)

        Args:
            html: Raw HTML content.
            output_format: Output format (markdown, text, html).
            include_images: Whether to include images in output.
            include_videos: Whether to include videos in output.
        """
        fmt_map = {
            "markdown": "markdown",
            "md": "markdown",
            "text": "txt",
            "txt": "txt",
            "html": "html",
        }
        fmt = fmt_map.get(output_format.lower(), "markdown")

        # Primary: trafilatura
        try:
            import trafilatura

            extracted = trafilatura.extract(
                html,
                output_format=fmt,
                include_comments=False,
                include_tables=True,
                include_links=True,
                include_images=include_images,
                deduplicate=True,
            )
            if extracted and len(extracted.strip()) > 50:
                return extracted
        except Exception:
            pass

        # Fallback: readability-lxml
        try:
            from readability import Document

            doc = Document(html)
            summary_html = doc.summary(html_partial=True)
            if not summary_html:
                return ""
            if fmt == "html":
                return summary_html
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(summary_html, "lxml")
            if fmt == "txt":
                return soup.get_text(separator="\n", strip=True)
            # For markdown, use trafilatura to convert readability's HTML
            try:
                import trafilatura

                md = trafilatura.extract(
                    summary_html,
                    output_format="markdown",
                    include_comments=False,
                    include_tables=True,
                    include_links=True,
                    include_images=include_images,
                )
                if md and len(md.strip()) > 20:
                    return md
            except Exception:
                pass
            return soup.get_text(separator="\n", strip=True)
        except Exception:
            pass

        # Final fallback: html2text (if available)
        try:
            import html2text

            h = html2text.HTML2Text()
            h.ignore_links = False
            h.ignore_images = not include_images
            h.body_width = 0
            text = h.handle(html)
            if text and len(text.strip()) > 50:
                return text
        except Exception:
            pass

        return ""
