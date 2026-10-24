"""Broken link checker module for webscout-mcp.
Detects broken links, invalid URLs, and link issues.

Features:
- Check link validity (HTTP status codes)
- Detect broken links (404, 500, etc.)
- Detect redirect chains
- Detect invalid URL formats
- Detect mixed content (HTTP on HTTPS pages)
- Internal vs external link classification
- Link depth analysis
- Anchor text analysis
- Concurrent link checking
- Configurable timeouts and retries
- Detailed reporting
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from .logging_config import get_logger
from .url_safety import UrlSafetyResult, check_url_safe

log = get_logger(__name__)


def _prepare_pinned_request(
    client: httpx.Client | httpx.AsyncClient,
    target_url: str,
    safety: UrlSafetyResult,
    user_agent: str,
) -> tuple[httpx.Request | None, str]:
    """Build a request pinned to the exact public IPs returned by the safety check.

    The TCP connection targets a literal verified IP, preventing a second DNS
    lookup from rebinding the destination. Host and TLS SNI preserve origin
    routing and certificate verification for HTTPS URLs.
    """
    target = httpx.URL(target_url)
    if target.userinfo:
        return None, "URLs containing embedded credentials are not allowed"

    if not safety.safe:
        return None, f"SSRF blocked: {safety.reason}"

    resolved_ips = safety.resolved_ips or []
    if not resolved_ips:
        return None, "SSRF blocked: safety check did not provide a resolved IP"

    # Prefer IPv4 when available because many hosts do not have working IPv6 egress.
    pinned_ip = next((ip for ip in resolved_ips if ":" not in ip), resolved_ips[0])
    pinned_url = target.copy_with(host=pinned_ip)
    original_authority = target.netloc.decode("ascii")
    headers = {"User-Agent": user_agent, "Host": original_authority}
    request = client.build_request("GET", pinned_url, headers=headers)

    if target.scheme == "https":
        try:
            original_host = target.host.encode("idna").decode("ascii")
        except UnicodeError:
            return None, "SSRF blocked: invalid internationalized hostname"
        request.extensions["sni_hostname"] = original_host

    return request, ""


@dataclass
class LinkCheckResult:
    """Result of checking a single link."""

    url: str
    status_code: int = 0
    status: str = "unknown"  # ok, broken, redirect, timeout, error, invalid, blocked
    final_url: str = ""
    redirect_count: int = 0
    redirect_chain: list[str] = field(default_factory=list)
    response_time_ms: float = 0.0
    error_message: str = ""
    anchor_text: str = ""
    link_type: str = "external"  # internal, external, mailto, tel, javascript
    is_mixed_content: bool = False
    depth: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "status": self.status,
            "final_url": self.final_url,
            "redirect_count": self.redirect_count,
            "redirect_chain": self.redirect_chain,
            "response_time_ms": self.response_time_ms,
            "error_message": self.error_message,
            "anchor_text": self.anchor_text,
            "link_type": self.link_type,
            "is_mixed_content": self.is_mixed_content,
            "depth": self.depth,
        }


@dataclass
class BrokenLinkReport:
    """Report of broken link check."""

    base_url: str = ""
    total_links: int = 0
    ok_links: int = 0
    broken_links: int = 0
    redirect_links: int = 0
    timeout_links: int = 0
    error_links: int = 0
    invalid_links: int = 0
    blocked_links: int = 0
    internal_links: int = 0
    external_links: int = 0
    mixed_content_links: int = 0
    results: list[LinkCheckResult] = field(default_factory=list)
    check_duration_ms: float = 0.0

    @property
    def broken_link_percentage(self) -> float:
        if self.total_links == 0:
            return 0.0
        return round(self.broken_links / self.total_links * 100, 1)

    def to_dict(self) -> dict:
        return {
            "base_url": self.base_url,
            "total_links": self.total_links,
            "ok_links": self.ok_links,
            "broken_links": self.broken_links,
            "redirect_links": self.redirect_links,
            "timeout_links": self.timeout_links,
            "error_links": self.error_links,
            "invalid_links": self.invalid_links,
            "blocked_links": self.blocked_links,
            "internal_links": self.internal_links,
            "external_links": self.external_links,
            "mixed_content_links": self.mixed_content_links,
            "broken_link_percentage": self.broken_link_percentage,
            "check_duration_ms": self.check_duration_ms,
            "results": [r.to_dict() for r in self.results],
        }


class BrokenLinkChecker:
    """Checks for broken links on web pages.

    Features:
    - HTTP status code checking
    - Redirect detection and chain analysis
    - Invalid URL detection
    - Mixed content detection
    - Internal/external link classification
    - Concurrent checking
    - Configurable timeouts and retries
    """

    # Special link schemes
    SPECIAL_SCHEMES = {"mailto:", "tel:", "javascript:", "#", "data:"}

    def __init__(
        self,
        timeout: float = 10.0,
        max_redirects: int = 5,
        verify_ssl: bool = True,
        user_agent: str = "Mozilla/5.0 (compatible; webscout-mcp/1.0)",
        max_concurrent: int = 10,
    ) -> None:
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.verify_ssl = verify_ssl
        self.user_agent = user_agent
        self.max_concurrent = max_concurrent

    def extract_links(self, html: str, base_url: str = "") -> list[dict]:
        """Extract links from HTML content.

        Args:
            html: HTML content.
            base_url: Base URL for resolving relative links.

        Returns:
            List of link dictionaries with url, anchor_text, link_type.
        """
        links = []
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            for a_tag in soup.find_all("a", href=True):
                href = a_tag.get("href", "").strip()
                anchor_text = a_tag.get_text(strip=True)

                if not href:
                    continue

                # Classify link type
                link_type = self._classify_link(href)

                # Resolve relative URLs
                if base_url and not href.startswith(
                    ("http://", "https://", "mailto:", "tel:", "javascript:", "#", "data:")
                ):
                    href = urljoin(base_url, href)

                links.append(
                    {
                        "url": href,
                        "anchor_text": anchor_text,
                        "link_type": link_type,
                    }
                )

        except ImportError:
            log.warning("BeautifulSoup not available for link extraction")

        return links

    def _classify_link(self, url: str) -> str:
        """Classify a link by type."""
        url_lower = url.lower()
        if url_lower.startswith("mailto:"):
            return "mailto"
        if url_lower.startswith("tel:"):
            return "tel"
        if url_lower.startswith("javascript:"):
            return "javascript"
        if url.startswith("#"):
            return "anchor"
        if url_lower.startswith("data:"):
            return "data"
        return "unknown"

    async def fetch_page_html(self, url: str, max_chars: int = 200000) -> tuple[str | None, str, str | None]:
        """Fetch the starting page with SSRF validation and DNS-pinned connections.

        Redirects are followed manually, validating and pinning each destination
        before a subsequent request is sent. The response body is byte-limited
        before decoding, then truncated to max_chars.
        """
        current_url = url
        try:
            target = httpx.URL(current_url)
            if target.userinfo:
                return None, current_url, "URLs containing embedded credentials are not allowed"

            safety = check_url_safe(current_url)
            if not safety.safe:
                return None, current_url, f"SSRF blocked: {safety.reason}"
            if not safety.resolved_ips:
                return None, current_url, "SSRF blocked: safety check did not provide a resolved IP"

            async with httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=False,
                verify=self.verify_ssl,
                headers={"User-Agent": self.user_agent},
            ) as client:
                for hop in range(self.max_redirects + 1):
                    request, request_error = _prepare_pinned_request(client, current_url, safety, self.user_agent)
                    if request is None:
                        return None, current_url, request_error

                    response = await client.send(request, follow_redirects=False, stream=True)
                    try:
                        status_code = response.status_code
                        if 300 <= status_code < 400:
                            location = response.headers.get("Location", "")
                            if not location:
                                return None, current_url, "Redirect with no Location header"
                            if hop >= self.max_redirects:
                                return None, current_url, f"Maximum redirects ({self.max_redirects}) exceeded"

                            redirect_url = urljoin(current_url, location)
                            redirect_target = httpx.URL(redirect_url)
                            if redirect_target.userinfo:
                                return None, redirect_url, "URLs containing embedded credentials are not allowed"

                            safety = check_url_safe(redirect_url)
                            if not safety.safe:
                                return None, redirect_url, f"SSRF blocked: {safety.reason}"
                            if not safety.resolved_ips:
                                return (
                                    None,
                                    redirect_url,
                                    "SSRF blocked: safety check did not provide a resolved IP",
                                )

                            current_url = redirect_url
                            continue

                        if not 200 <= status_code < 300:
                            return None, current_url, f"HTTP {status_code}"

                        max_bytes = max(1, max_chars * 4)
                        chunks: list[bytes] = []
                        total_bytes = 0
                        async for chunk in response.aiter_bytes():
                            remaining = max_bytes - total_bytes
                            if remaining <= 0:
                                break
                            part = chunk[:remaining]
                            chunks.append(part)
                            total_bytes += len(part)
                            if total_bytes >= max_bytes:
                                break

                        payload = b"".join(chunks)
                        encoding = response.encoding or "utf-8"
                        try:
                            html = payload.decode(encoding, errors="replace")
                        except LookupError:
                            html = payload.decode("utf-8", errors="replace")
                        return html[:max_chars], current_url, None
                    finally:
                        await response.aclose()

            return None, current_url, f"Maximum redirects ({self.max_redirects}) exceeded"

        except httpx.TimeoutException:
            return None, current_url, f"Request timed out after {self.timeout}s"
        except Exception as exc:
            return None, current_url, f"Safe page fetch failed: {type(exc).__name__}: {exc}"

    def check_link(self, url: str, base_url: str = "", anchor_text: str = "") -> LinkCheckResult:
        """Check a single link.

        Args:
            url: URL to check.
            base_url: Base URL of the page.
            anchor_text: Anchor text of the link.

        Returns:
            LinkCheckResult with check results.
        """
        import time

        result = LinkCheckResult(url=url, anchor_text=anchor_text)

        # Validate URL format
        if not self._is_valid_url(url):
            result.status = "invalid"
            result.error_message = "Invalid URL format"
            return result

        # Skip special links
        parsed = urlparse(url)
        if parsed.scheme in ("mailto", "tel", "javascript", "data"):
            result.status = "ok"
            result.link_type = parsed.scheme
            return result

        # Determine if internal or external
        if base_url:
            base_parsed = urlparse(base_url)
            if parsed.netloc == base_parsed.netloc or not parsed.netloc:
                result.link_type = "internal"
            else:
                result.link_type = "external"

        # Check for mixed content
        if base_url and base_url.startswith("https://") and url.startswith("http://"):
            result.is_mixed_content = True

        # Perform HTTP request
        start_time = time.time()
        try:
            redirect_count = 0
            current_url = url
            redirect_chain = [url]

            # Validate the initial destination and pin the actual connection before
            # creating/sending any request to it.
            initial_safety = check_url_safe(current_url)
            if not initial_safety.safe:
                result.status = "blocked"
                result.final_url = current_url
                result.error_message = f"SSRF blocked: {initial_safety.reason}"
            elif not initial_safety.resolved_ips:
                result.status = "blocked"
                result.final_url = current_url
                result.error_message = "SSRF blocked: safety check did not provide a resolved IP"
            elif httpx.URL(current_url).userinfo:
                result.status = "blocked"
                result.final_url = current_url
                result.error_message = "URLs containing embedded credentials are not allowed"
            else:
                headers = {"User-Agent": self.user_agent}

                with httpx.Client(
                    timeout=self.timeout,
                    follow_redirects=False,
                    verify=self.verify_ssl,
                    headers=headers,
                ) as client:
                    safety = initial_safety
                    while redirect_count < self.max_redirects:
                        request, request_error = _prepare_pinned_request(client, current_url, safety, self.user_agent)
                        if request is None:
                            result.status = "blocked"
                            result.final_url = current_url
                            result.error_message = request_error
                            break

                        response = client.send(request, follow_redirects=False)
                        result.status_code = response.status_code

                        if 300 <= response.status_code < 400:
                            location = response.headers.get("Location", "")
                            if location:
                                current_url = urljoin(current_url, location)
                                redirect_chain.append(current_url)
                                redirect_count += 1
                                # Validate the redirect exactly once and carry the resolved
                                # IP into the pinned request on the next loop iteration.
                                safety = check_url_safe(current_url)
                                redirect_target = httpx.URL(current_url)
                                if redirect_target.userinfo:
                                    result.status = "blocked"
                                    result.final_url = current_url
                                    result.error_message = "URLs containing embedded credentials are not allowed"
                                    break
                                if not safety.safe:
                                    result.status = "blocked"
                                    result.final_url = current_url
                                    result.error_message = f"SSRF blocked: {safety.reason}"
                                    break
                                if not safety.resolved_ips:
                                    result.status = "blocked"
                                    result.final_url = current_url
                                    result.error_message = "SSRF blocked: safety check did not provide a resolved IP"
                                    break
                                continue
                            else:
                                result.status = "error"
                                result.error_message = "Redirect with no Location header"
                                break

                        elif response.status_code == 200:
                            result.status = "ok"
                            result.final_url = current_url
                            break

                        elif 400 <= response.status_code < 500:
                            result.status = "broken"
                            result.final_url = current_url
                            result.error_message = f"Client error: {response.status_code}"
                            break

                        elif response.status_code >= 500:
                            result.status = "broken"
                            result.final_url = current_url
                            result.error_message = f"Server error: {response.status_code}"
                            break

                        else:
                            result.status = "unknown"
                            result.final_url = current_url
                            break

            result.redirect_count = redirect_count
            result.redirect_chain = redirect_chain
            if redirect_count > 0 and result.status != "blocked":
                result.status = "redirect"

        except httpx.TimeoutException:
            result.status = "timeout"
            result.error_message = f"Request timed out after {self.timeout}s"

        except httpx.ConnectError as exc:
            result.status = "error"
            result.error_message = f"Connection error: {exc}"

        except Exception as exc:
            result.status = "error"
            result.error_message = f"Error: {exc}"

        result.response_time_ms = round((time.time() - start_time) * 1000, 2)
        return result

    def _is_valid_url(self, url: str) -> bool:
        """Check if URL has valid format."""
        if not url:
            return False

        # Check for special schemes
        if any(url.lower().startswith(scheme) for scheme in self.SPECIAL_SCHEMES):
            return True

        # Check for valid HTTP/HTTPS URL
        try:
            parsed = urlparse(url)
            return parsed.scheme in ("http", "https") and bool(parsed.netloc)
        except Exception:
            return False

    def check_page(self, html: str, base_url: str = "") -> BrokenLinkReport:
        """Check all links on a page.

        Args:
            html: HTML content of the page.
            base_url: Base URL of the page.

        Returns:
            BrokenLinkReport with check results.
        """
        import time

        report = BrokenLinkReport(base_url=base_url)
        start_time = time.time()

        # Extract links
        links = self.extract_links(html, base_url)
        report.total_links = len(links)

        # Check each link
        for link in links:
            result = self.check_link(
                url=link["url"],
                base_url=base_url,
                anchor_text=link["anchor_text"],
            )
            result.link_type = link["link_type"] if result.link_type == "unknown" else result.link_type
            report.results.append(result)

            # Update counters
            if result.status == "ok":
                report.ok_links += 1
            elif result.status == "broken":
                report.broken_links += 1
            elif result.status == "redirect":
                report.redirect_links += 1
            elif result.status == "timeout":
                report.timeout_links += 1
            elif result.status == "error":
                report.error_links += 1
            elif result.status == "invalid":
                report.invalid_links += 1
            elif result.status == "blocked":
                report.blocked_links += 1

            if result.link_type == "internal":
                report.internal_links += 1
            elif result.link_type == "external":
                report.external_links += 1

            if result.is_mixed_content:
                report.mixed_content_links += 1

        report.check_duration_ms = round((time.time() - start_time) * 1000, 2)
        return report

    def get_broken_links(self, report: BrokenLinkReport) -> list[LinkCheckResult]:
        """Get only broken links from report.

        Args:
            report: Broken link report.

        Returns:
            List of broken link results.
        """
        return [r for r in report.results if r.status in ("broken", "timeout", "error", "invalid")]

    def generate_summary(self, report: BrokenLinkReport) -> str:
        """Generate a human-readable summary of the report.

        Args:
            report: Broken link report.

        Returns:
            Summary string.
        """
        lines = [
            f"Broken Link Check Report for: {report.base_url}",
            "=" * 60,
            f"Total links checked: {report.total_links}",
            f"OK: {report.ok_links}",
            f"Broken: {report.broken_links}",
            f"Redirects: {report.redirect_links}",
            f"Timeouts: {report.timeout_links}",
            f"Errors: {report.error_links}",
            f"Invalid: {report.invalid_links}",
            f"Blocked (SSRF safety): {report.blocked_links}",
            "",
            f"Internal links: {report.internal_links}",
            f"External links: {report.external_links}",
            f"Mixed content: {report.mixed_content_links}",
            "",
            f"Broken link percentage: {report.broken_link_percentage}%",
            f"Check duration: {report.check_duration_ms}ms",
        ]

        broken = self.get_broken_links(report)
        if broken:
            lines.append("")
            lines.append("Broken Links:")
            lines.append("-" * 60)
            for link in broken:
                lines.append(f"  [{link.status.upper()}] {link.url}")
                if link.error_message:
                    lines.append(f"    Error: {link.error_message}")
                if link.anchor_text:
                    lines.append(f"    Anchor: {link.anchor_text}")

        blocked = [r for r in report.results if r.status == "blocked"]
        if blocked:
            lines.append("")
            lines.append("Blocked Links (not requested for safety):")
            lines.append("-" * 60)
            for link in blocked:
                lines.append(f"  [BLOCKED] {link.url}")
                if link.error_message:
                    lines.append(f"    Reason: {link.error_message}")
                if link.anchor_text:
                    lines.append(f"    Anchor: {link.anchor_text}")

        return "\n".join(lines)


def check_broken_links(html: str, base_url: str = "", timeout: float = 10.0) -> BrokenLinkReport:
    """Convenience function to check broken links.

    Args:
        html: HTML content.
        base_url: Base URL.
        timeout: Request timeout in seconds.

    Returns:
        BrokenLinkReport with check results.
    """
    checker = BrokenLinkChecker(timeout=timeout)
    return checker.check_page(html, base_url)
