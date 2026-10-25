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

import ipaddress
import socket
import time
from typing import Any

import httpx

from .core.errors import StandardErrorCode
from .fetch_provider import (
    BrowserFetchProvider,
    FetchRequest,
    FetchResponse,
)
from .logging_config import get_logger
from .observability import record_fetch_attempt, record_ssrf_block
from .url_safety import assert_redirect_chain_safe

log = get_logger(__name__)

DEFAULT_TIMEOUT = 30.0
MAX_RESPONSE_BYTES = 2_000_000  # 2 MB cap on returned content

# Per-address budget for the reachability probe. Kept small: this runs at
# registration, before any request is served, and a sidecar that is not up
# should not delay startup.
_PROBE_CONNECT_TIMEOUT = 0.5

# Address ranges that never host a real sidecar but DO accept connections on
# hosts running a proxy in TUN/fake-IP mode. FlClash/Clash resolve every name -
# including reserved ones like *.invalid - into 198.18.0.0/15 and then accept the
# connection themselves, which would make a naive probe report "reachable" for a
# sidecar that does not exist.
#
# A sidecar is reached by an explicit configured base_url, so localhost and LAN
# addresses remain valid targets; only the fake-IP ranges are rejected.
_FAKE_IP_NETWORKS = (
    ipaddress.ip_network("198.18.0.0/15"),  # RFC 2544 benchmarking, used by fake-IP DNS
)


def _is_fake_ip(addr: str) -> bool:
    """True when ``addr`` falls in a range that only a proxy would answer on."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in _FAKE_IP_NETWORKS)


def _tcp_reachable(base_url: str, timeout: float = _PROBE_CONNECT_TIMEOUT) -> bool:
    """True when a TCP connection to ``base_url``'s host:port succeeds.

    Bounded by ``timeout`` in total, not per resolved address. ``httpx`` and
    ``socket.create_connection`` both apply the timeout to each address in turn,
    so a name resolving to ::1 and 127.0.0.1 can take twice the budget. Here the
    addresses are walked explicitly with a deadline.

    Addresses inside a fake-IP range are skipped rather than connected: on such a
    host the proxy answers for any name, so connecting would prove only that the
    proxy exists (see _FAKE_IP_NETWORKS).

    Any connection that opens counts, whatever the server would answer: a 404 or
    500 proves the sidecar is running, and this is a liveness check.

    Isolated at module level so tests can monkeypatch it without a socket.
    """
    from urllib.parse import urlparse

    parsed = urlparse(base_url)
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return False

    deadline = time.monotonic() + timeout
    for family, socktype, proto, _canon, sockaddr in infos:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if _is_fake_ip(str(sockaddr[0])):
            continue
        sock = None
        try:
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(remaining)
            sock.connect(sockaddr)
            return True
        except OSError:
            continue
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
    return False


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
        # Cache for the reachability probe. None means "not probed yet".
        self._reachable: bool | None = None

    @property
    def is_configured(self) -> bool:
        """Whether a sidecar is configured. Says nothing about reachability."""
        return self.enabled

    def probe_reachable(self, timeout: float = 0.5) -> bool:
        """Ask the sidecar whether it is actually there, once.

        ``is_available`` used to return ``enabled`` while its docstring claimed
        "configured and reachable". With ``crawl4ai_enabled=true`` and a
        ``base_url`` pointing at a sidecar that was not running, the backend was
        still registered and every SPA-shaped page paid a real round trip to a
        service that did not exist - failing, falling back, and preserving the
        content, so nothing looked broken while the latency was wasted each
        time.

        Implemented as a plain TCP connect rather than an HTTP GET, for a
        measured reason: ``httpx.get(timeout=1.5)`` against an unreachable
        localhost took 3509ms here, because the timeout applies per resolved
        address (::1 then 127.0.0.1) and this host silently drops the SYN
        instead of refusing it. A connect loop with a per-address timeout bounds
        the whole probe to ``timeout`` regardless of how many addresses the name
        resolves to.

        Only the connection is checked. Any TCP accept counts as reachable: the
        sidecar answering with 404 or 500 still proves it is running, and this
        is a liveness check, not a health check.

        The result is memoised, so at most one probe happens per process and a
        failure is not retried on every request.
        """
        if self._reachable is not None:
            return self._reachable
        if not self.enabled:
            self._reachable = False
            return False

        self._reachable = _tcp_reachable(self.base_url, timeout)
        if not self._reachable:
            log.warning(
                "Crawl4AI sidecar configured at %s but not reachable; browser escalation disabled for this process",
                self.base_url,
            )
        return self._reachable

    @property
    def is_available(self) -> bool:
        """Whether the sidecar is configured AND actually answering.

        Probes once and memoises. Callers use this to decide whether to register
        the backend as a BROWSER provider, so returning ``enabled`` alone meant
        registering a provider that could never succeed.
        """
        return self.probe_reachable()

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

        # SSRF guard: refuse to drive the sidecar at loopback / private /
        # link-local / metadata targets unless explicitly opted in.
        allow_private = bool(getattr(self.config, "crawl4ai_allow_private", False))
        safety = await assert_redirect_chain_safe(request.url, allow_private=allow_private, timeout=5.0)
        if not safety.safe:
            try:
                record_ssrf_block(safety.reason or "unknown")
            except Exception:  # pragma: no cover - observability must not break fetch
                log.exception("observability record_ssrf_block failed")
            return FetchResponse(
                url=request.url,
                final_url=request.url,
                status_code=403,
                provider=self.name,
                error=f"Blocked by SSRF guard: {safety.reason}",
                latency_ms=self._measure_latency(start),
                error_code=StandardErrorCode.FETCH_FORBIDDEN,
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
                return self._record_and_return(
                    start,
                    FetchResponse(
                        url=request.url,
                        final_url=request.url,
                        status_code=resp.status_code,
                        provider=self.name,
                        error=f"Crawl4AI auth error: {resp.status_code}",
                        latency_ms=self._measure_latency(start),
                        error_code=StandardErrorCode.FETCH_FORBIDDEN,
                        retryable=False,
                    ),
                    result="forbidden",
                )
            if resp.status_code == 429:
                return self._record_and_return(
                    start,
                    FetchResponse(
                        url=request.url,
                        final_url=request.url,
                        status_code=429,
                        provider=self.name,
                        error="Crawl4AI rate limited",
                        latency_ms=self._measure_latency(start),
                        error_code=StandardErrorCode.FETCH_RATE_LIMITED,
                        retryable=True,
                    ),
                    result="failure",
                    reason="rate_limited",
                )
            if resp.status_code >= 500:
                return self._record_and_return(
                    start,
                    FetchResponse(
                        url=request.url,
                        final_url=request.url,
                        status_code=resp.status_code,
                        provider=self.name,
                        error=f"Crawl4AI server error: {resp.status_code}",
                        latency_ms=self._measure_latency(start),
                        error_code=StandardErrorCode.FETCH_SERVER_ERROR,
                        retryable=True,
                    ),
                    result="failure",
                    reason="server_error",
                )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results") or []
            if not results:
                return self._record_and_return(
                    start,
                    FetchResponse(
                        url=request.url,
                        final_url=request.url,
                        status_code=200,
                        provider=self.name,
                        error="Crawl4AI returned no results",
                        latency_ms=self._measure_latency(start),
                        error_code=StandardErrorCode.FETCH_FAILED,
                        retryable=True,
                    ),
                    result="failure",
                    reason="no_results",
                )

            r = results[0]
            content = r.get("markdown") or r.get("extracted_content") or r.get("html") or ""
            if isinstance(content, dict):
                # Some Crawl4AI versions wrap markdown under .raw_markdown / .fit_markdown
                content = content.get("raw_markdown") or content.get("fit_markdown") or ""
            content = str(content)[:MAX_RESPONSE_BYTES]
            metadata = r.get("metadata") or {}

            return self._record_and_return(
                start,
                FetchResponse(
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
                ),
                result="success",
            )

        except httpx.TimeoutException:
            return self._record_and_return(
                start,
                FetchResponse(
                    url=request.url,
                    final_url=request.url,
                    status_code=0,
                    provider=self.name,
                    error=f"Crawl4AI timed out after {self.timeout}s",
                    latency_ms=self._measure_latency(start),
                    error_code=StandardErrorCode.FETCH_TIMEOUT,
                    retryable=True,
                ),
                result="timeout",
            )
        except httpx.ConnectError:
            return self._record_and_return(
                start,
                FetchResponse(
                    url=request.url,
                    final_url=request.url,
                    status_code=0,
                    provider=self.name,
                    error="Could not connect to Crawl4AI sidecar",
                    latency_ms=self._measure_latency(start),
                    error_code=StandardErrorCode.FETCH_CONNECTION_ERROR,
                    retryable=True,
                ),
                result="failure",
                reason="connect_error",
            )
        except Exception as e:  # noqa: BLE001
            log.exception("Crawl4AI fetch error")
            return self._record_and_return(
                start,
                FetchResponse(
                    url=request.url,
                    final_url=request.url,
                    status_code=0,
                    provider=self.name,
                    error=f"{type(e).__name__}: {e}",
                    latency_ms=self._measure_latency(start),
                    error_code=StandardErrorCode.FETCH_FAILED,
                    retryable=True,
                ),
                result="failure",
                reason="exception",
            )

    def _record_and_return(
        self,
        start: float,
        response: FetchResponse,
        *,
        result: str,
        reason: str | None = None,
    ) -> FetchResponse:
        """Observability wrapper. Never raises."""
        try:
            record_fetch_attempt(
                "crawl4ai",
                result=result,
                latency_ms=response.latency_ms,
                reason=reason,
            )
        except Exception:  # pragma: no cover
            log.exception("observability record_fetch_attempt failed")
        return response

    async def health(self):  # type: ignore[override]
        from .search_provider import ProviderHealthStatus

        if not self.enabled:
            self._health.status = ProviderHealthStatus.UNKNOWN
        return self._health

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
