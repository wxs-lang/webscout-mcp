"""TLS fingerprint-aware fetcher using curl_cffi.
This module provides a fetcher that can impersonate real browser TLS fingerprints,
helping to bypass anti-bot systems that detect TLS fingerprint differences.

Supported browser impersonations:
- chrome99, chrome100, chrome101, chrome104, chrome107, chrome110, chrome116, chrome119, chrome120
- firefox98, firefox101, firefox102, firefox105, firefox108, firefox110, firefox117, firefox119, firefox120
- safari15_3, safari15_5, safari16_0, safari17_0
- edge99, edge101, edge104
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    from curl_cffi import requests as curl_requests
    from curl_cffi.requests import Response

    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False


@dataclass
class TLSFetchResult:
    """Result of a TLS-aware fetch operation."""

    url: str
    final_url: str
    status_code: int
    content: str = ""
    content_type: str = ""
    headers: dict = field(default_factory=dict)
    error: str | None = None
    impersonated_browser: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status_code": self.status_code,
            "content": self.content,
            "content_type": self.content_type,
            "headers": self.headers,
            "error": self.error,
            "impersonated_browser": self.impersonated_browser,
        }


class TLSFetcher:
    """TLS fingerprint-aware fetcher using curl_cffi.

    This fetcher impersonates real browser TLS fingerprints to bypass anti-bot
    systems that detect TLS fingerprint differences. It can be used as a fallback
    when the standard httpx-based fetcher is blocked.

    Args:
        impersonate: Browser to impersonate (e.g., 'chrome120', 'firefox120', 'safari17_0').
        timeout: Request timeout in seconds.
        max_redirects: Maximum number of redirects to follow.
        verify: Whether to verify SSL certificates.
    """

    SUPPORTED_BROWSERS = [
        "chrome99",
        "chrome100",
        "chrome101",
        "chrome104",
        "chrome107",
        "chrome110",
        "chrome116",
        "chrome119",
        "chrome120",
        "firefox98",
        "firefox101",
        "firefox102",
        "firefox105",
        "firefox108",
        "firefox110",
        "firefox117",
        "firefox119",
        "firefox120",
        "safari15_3",
        "safari15_5",
        "safari16_0",
        "safari17_0",
        "edge99",
        "edge101",
        "edge104",
    ]

    def __init__(
        self,
        impersonate: str = "chrome120",
        timeout: float = 30.0,
        max_redirects: int = 5,
        verify: bool = True,
    ) -> None:
        if not HAS_CURL_CFFI:
            raise ImportError("curl_cffi is not installed. Install it with: pip install curl_cffi")
        if impersonate not in self.SUPPORTED_BROWSERS:
            raise ValueError(f"Unsupported browser: {impersonate}. Supported: {', '.join(self.SUPPORTED_BROWSERS)}")
        self.impersonate = impersonate
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.verify = verify
        self._session = curl_requests.Session(
            impersonate=impersonate,
            timeout=timeout,
            max_redirects=max_redirects,
            verify=verify,
        )

    def fetch(
        self,
        url: str,
        headers: dict | None = None,
        params: dict | None = None,
        data: dict | None = None,
        method: str = "GET",
    ) -> TLSFetchResult:
        """Fetch a URL with TLS fingerprint impersonation.

        Args:
            url: URL to fetch.
            headers: Optional HTTP headers.
            params: Optional query parameters.
            data: Optional request body data.
            method: HTTP method (GET, POST, etc.).

        Returns:
            TLSFetchResult with the response data.
        """
        try:
            response = self._session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                data=data,
            )
            return TLSFetchResult(
                url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                content=response.text,
                content_type=response.headers.get("content-type", ""),
                headers=dict(response.headers),
                impersonated_browser=self.impersonate,
            )
        except Exception as exc:
            return TLSFetchResult(
                url=url,
                final_url=url,
                status_code=0,
                error=f"{type(exc).__name__}: {exc}",
                impersonated_browser=self.impersonate,
            )

    def close(self) -> None:
        """Close the underlying session."""
        if self._session:
            self._session.close()

    def __enter__(self) -> TLSFetcher:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def is_tls_fetcher_available() -> bool:
    """Check if curl_cffi is available for TLS fingerprint impersonation."""
    return HAS_CURL_CFFI


def get_supported_browsers() -> list[str]:
    """Get list of supported browser impersonations."""
    return TLSFetcher.SUPPORTED_BROWSERS if HAS_CURL_CFFI else []
