"""Custom exceptions for webscout-mcp.

All exceptions inherit from :class:`WebScoutError` so callers can catch
the entire hierarchy with a single ``except`` clause.
"""
from __future__ import annotations


class WebScoutError(Exception):
    """Base class for all webscout-mcp errors."""


class FetchError(WebScoutError):
    """Base class for fetch-related errors."""

    def __init__(self, url: str, message: str = "") -> None:
        self.url = url
        super().__init__(message or f"Failed to fetch {url}")


class TimeoutError(FetchError):
    """The request timed out."""

    def __init__(self, url: str, timeout: float | None = None) -> None:
        msg = f"Request to {url} timed out"
        if timeout is not None:
            msg += f" after {timeout}s"
        super().__init__(url, msg)
        self.timeout = timeout


class HTTPError(FetchError):
    """The server returned an HTTP error status."""

    def __init__(self, url: str, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(url, message or f"HTTP {status_code} for {url}")


class ForbiddenError(HTTPError):
    """The server returned 403 Forbidden."""

    def __init__(self, url: str, message: str = "") -> None:
        super().__init__(url, 403, message or f"403 Forbidden for {url}")


class NotFoundError(HTTPError):
    """The server returned 404 Not Found."""

    def __init__(self, url: str, message: str = "") -> None:
        super().__init__(url, 404, message or f"404 Not Found: {url}")


class ContentTooLargeError(FetchError):
    """The response body exceeds the configured maximum size."""

    def __init__(self, url: str, content_length: int, max_length: int) -> None:
        self.content_length = content_length
        self.max_length = max_length
        super().__init__(
            url,
            f"Content too large: {content_length} bytes (limit {max_length})",
        )


class SearchError(WebScoutError):
    """Base class for search-related errors."""

    def __init__(self, query: str, backend: str = "", message: str = "") -> None:
        self.query = query
        self.backend = backend
        super().__init__(message or f"Search failed for query: {query}")


class AllBackendsFailedError(SearchError):
    """Every configured search backend failed."""

    def __init__(self, query: str, failures: dict[str, str]) -> None:
        self.failures = failures
        details = ", ".join(f"{k}: {v}" for k, v in failures.items())
        super().__init__(query, "all", f"All search backends failed — {details}")


class RobotsTxtError(WebScoutError):
    """Base class for robots.txt related errors."""


class DisallowedByRobotsError(RobotsTxtError):
    """The URL is disallowed by the site's robots.txt."""

    def __init__(self, url: str, user_agent: str = "*") -> None:
        self.url = url
        self.user_agent = user_agent
        super().__init__(f"URL disallowed by robots.txt: {url} (UA: {user_agent})")


class ExtractionError(WebScoutError):
    """Structured data extraction failed."""

    def __init__(self, rule_name: str, message: str = "") -> None:
        self.rule_name = rule_name
        super().__init__(message or f"Extraction failed for rule: {rule_name}")


class CrawlError(WebScoutError):
    """Crawl operation encountered a fatal error."""
