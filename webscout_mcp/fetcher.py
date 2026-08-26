"""Smart web fetcher with retry, caching, rate-limiting, and content extraction.

This is the workhorse of webscout-mcp.  It fetches a URL, optionally extracts
the main article content (via ``trafilatura``), and returns structured data.
All network calls go through the rate limiter and cache.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional

import httpx

from .cache import Cache
from .config import Config
from .utils import TokenBucket, normalize_url, truncate_text


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
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

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
        }


class Fetcher:
    """Async web fetcher with intelligent defaults."""

    def __init__(self, config: Config, cache: Optional[Cache] = None):
        self.config = config
        self.cache = cache
        self.rate_limiter = TokenBucket(
            rate=config.rate_limit_per_second,
            burst=config.rate_limit_burst,
        )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.request_timeout),
                follow_redirects=True,
                headers={"User-Agent": self.config.user_agent},
                max_redirects=5,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def fetch(
        self,
        url: str,
        extract: bool = True,
        output_format: Optional[str] = None,
        max_chars: Optional[int] = None,
        bypass_cache: bool = False,
    ) -> FetchResult:
        """Fetch a URL and optionally extract main content.

        Args:
            url: The URL to fetch.
            extract: If True, extract main article content via trafilatura.
            output_format: ``markdown``, ``text``, or ``html`` (default from config).
            max_chars: Truncate content to this many characters.
            bypass_cache: If True, skip cache read (still writes to cache).

        Returns:
            A ``FetchResult`` with the fetched (and optionally extracted) content.
        """
        url = normalize_url(url)
        fmt = output_format or self.config.extract_output_format
        cache_key = f"fetch:{url}:{extract}:{fmt}"

        # Check cache
        if not bypass_cache and self.cache:
            cached = self.cache.get(cache_key)
            if cached:
                import json
                data = json.loads(cached["value"])
                result = FetchResult(**data)
                result.cached = True
                return result

        # Rate limit
        await self.rate_limiter.acquire(url)

        # Perform request with retries
        result = await self._fetch_with_retry(url)

        if result.error is None and result.content:
            # Extract main content if requested
            if extract and "text" in (result.content_type or "").lower():
                extracted = await asyncio.to_thread(
                    self._extract_content, result.content, fmt
                )
                if extracted:
                    result.content = extracted
                    result.extracted = True

            # Truncate
            limit = max_chars or 8000
            result.content = truncate_text(result.content, limit)

        # Store in cache
        if self.cache and result.error is None and result.status_code < 400:
            import json
            self.cache.set(
                cache_key,
                json.dumps(result.to_dict()),
                content_type="application/json",
            )

        return result

    async def _fetch_with_retry(self, url: str) -> FetchResult:
        """Fetch with exponential backoff retry."""
        last_error: Optional[Exception] = None
        for attempt in range(self.config.max_retries):
            try:
                client = await self._get_client()
                response = await client.get(url)

                # Check content length
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
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_backoff * (2 ** attempt))
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_backoff * (2 ** attempt))
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
    def _extract_title(html: str) -> str:
        """Extract the <title> from HTML."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
            if soup.title and soup.title.string:
                return soup.title.string.strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _extract_content(html: str, output_format: str = "markdown") -> str:
        """Extract main article content using trafilatura.

        Args:
            html: Raw HTML.
            output_format: ``markdown``, ``txt``, or ``html``.

        Returns:
            Extracted content, or empty string if extraction failed.
        """
        try:
            import trafilatura
            fmt_map = {
                "markdown": "markdown",
                "md": "markdown",
                "text": "txt",
                "txt": "txt",
                "html": "html",
            }
            fmt = fmt_map.get(output_format.lower(), "markdown")
            extracted = trafilatura.extract(
                html,
                output_format=fmt,
                include_comments=False,
                include_tables=True,
                include_links=True,
                deduplicate=True,
            )
            return extracted or ""
        except Exception:
            return ""
