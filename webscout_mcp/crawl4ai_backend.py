"""Crawl4AI HTTP sidecar backend for browser-based fetch.

Implements :class:`BrowserFetchProvider` by talking to a Crawl4AI FastAPI
sidecar over HTTP. Crawl4AI itself is a heavyweight browser-automation
runtime (Playwright/Chromium) and is intentionally NOT a Python dependency
of webscout-mcp; it runs as a separate container.

Configuration (environment variables):
    CRAWL4AI_BASE_URL   e.g. http://localhost:11235
    CRAWL4AI_API_TOKEN  Bearer token (recommended; required if sidecar
                        enforces auth)
    CRAWL4AI_TIMEOUT    request timeout in seconds (default 30.0)
    CRAWL4AI_ENABLED    set to "true" to opt in (default: disabled)

Scope for v1.2.2 (locked):
    One URL in -> rendered markdown/html out. No deep crawl, no screenshots,
    no PDF, no arbitrary JS, no LLM extraction. Those belong to later
    minors if there is real demand.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .errors import StandardErrorCode
from .fetch_provider import (
    BrowserFetchProvider,
    FetchRequest,
    FetchResponse,
)
from .logging_config import get_logger

log = get_logger(__name__)

DEFAULT_TIMEOUT = 30.0
MAX_RESPONSE_BYTES = 2_000_000  # 2 MB cap on returned content


class Crawl4AIBrowserBackend(BrowserFetchProvider):
    """Browser fetch backed by a remote Crawl4AI HTTP service."""

    name = "crawl4ai"

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.base_url = (getattr(config, "crawl4ai_base_url", "") or "").rstrip("/")
        self.api_token = getattr(config, "crawl4ai_api_token", "") or ""
        self.timeout = float(getattr(config, "crawl4ai_timeout", DEFAULT_TIMEOUT))
        self.enabled = bool(getattr(config, "crawl4ai_enabled", False)) and bool(self.base_url)
        self._client: httpx.AsyncClient | None = None

    @property
    def is_available(self) -> bool:
        """Whether the sidecar is configured and reachable."""
        return self.enabled

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/json"}
            if self.api_token:
                headers["Authorization"] = f"Bearer {self.api_token}"
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=headers)
        return self._client

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        start = time.time()
        if not self.enabled:
            return FetchResponse(
                url=request.url,
                final_url=request.url,
                status_code=0,
                provider=self.name,
                error="Crawl4AI sidecar not configured",
                latency_ms=self._measure_latency(start),
                error_code=StandardErrorCode.SYSTEM_CONFIG_ERROR,
                retryable=False,
            )

        try:
            client = await self._get_client()
            # Crawl4AI's /crawl endpoint accepts a list of URLs; we send one.
            payload = {
                "urls": [request.url],
                "browser_config": {"headless": True},
                "crawl_config": {"word_count_threshold": 1},
            }
            resp = await client.post(f"{self.base_url}/crawl", json=payload)

            if resp.status_code == 401 or resp.status_code == 403:
                return FetchResponse(
                    url=request.url,
                    final_url=request.url,
                    status_code=resp.status_code,
                    provider=self.name,
                    error=f"Crawl4AI auth error: {resp.status_code}",
                    latency_ms=self._measure_latency(start),
                    error_code=StandardErrorCode.FETCH_FORBIDDEN,
                    retryable=False,
                )
            if resp.status_code == 429:
                return FetchResponse(
                    url=request.url,
                    final_url=request.url,
                    status_code=429,
                    provider=self.name,
                    error="Crawl4AI rate limited",
                    latency_ms=self._measure_latency(start),
                    error_code=StandardErrorCode.FETCH_RATE_LIMITED,
                    retryable=True,
                )
            if resp.status_code >= 500:
                return FetchResponse(
                    url=request.url,
                    final_url=request.url,
                    status_code=resp.status_code,
                    provider=self.name,
                    error=f"Crawl4AI server error: {resp.status_code}",
                    latency_ms=self._measure_latency(start),
                    error_code=StandardErrorCode.FETCH_SERVER_ERROR,
                    retryable=True,
                )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results") or []
            if not results:
                return FetchResponse(
                    url=request.url,
                    final_url=request.url,
                    status_code=200,
                    provider=self.name,
                    error="Crawl4AI returned no results",
                    latency_ms=self._measure_latency(start),
                    error_code=StandardErrorCode.FETCH_FAILED,
                    retryable=True,
                )

            r = results[0]
            content = r.get("markdown") or r.get("extracted_content") or r.get("html") or ""
            if isinstance(content, dict):
                # Some Crawl4AI versions wrap markdown under .raw_markdown / .fit_markdown
                content = content.get("raw_markdown") or content.get("fit_markdown") or ""
            content = str(content)[:MAX_RESPONSE_BYTES]
            metadata = r.get("metadata") or {}

            return FetchResponse(
                url=request.url,
                final_url=metadata.get("url") or request.url,
                status_code=200,
                provider=self.name,
                title=metadata.get("title", ""),
                content=content,
                content_type="text/markdown",
                extracted=True,
                latency_ms=self._measure_latency(start),
                metadata={
                    "browser": "crawl4ai",
                    **{k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool))},
                },
            )

        except httpx.TimeoutException:
            return FetchResponse(
                url=request.url,
                final_url=request.url,
                status_code=0,
                provider=self.name,
                error=f"Crawl4AI timed out after {self.timeout}s",
                latency_ms=self._measure_latency(start),
                error_code=StandardErrorCode.FETCH_TIMEOUT,
                retryable=True,
            )
        except httpx.ConnectError:
            return FetchResponse(
                url=request.url,
                final_url=request.url,
                status_code=0,
                provider=self.name,
                error="Could not connect to Crawl4AI sidecar",
                latency_ms=self._measure_latency(start),
                error_code=StandardErrorCode.FETCH_CONNECTION_ERROR,
                retryable=True,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Crawl4AI fetch error")
            return FetchResponse(
                url=request.url,
                final_url=request.url,
                status_code=0,
                provider=self.name,
                error=f"{type(e).__name__}: {e}",
                latency_ms=self._measure_latency(start),
                error_code=StandardErrorCode.FETCH_FAILED,
                retryable=True,
            )

    async def health(self):  # type: ignore[override]
        from .search_provider import ProviderHealthStatus

        if not self.enabled:
            self._health.status = ProviderHealthStatus.UNKNOWN
        return self._health

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
