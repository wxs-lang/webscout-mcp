"""Security module for webscout-mcp.

Provides security utilities including SSRF protection, input validation,
rate limiting, and sensitive data filtering.

Features:
- SSRF protection (block internal IPs, private networks)
- Input validation (URL, file path, size limits)
- Rate limiting (token bucket, sliding window)
- Sensitive data filtering (API keys, passwords, tokens)
- Security headers configuration
- Content security policy
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

from .errors import InputValidationError, RateLimitError, SensitiveDataError, SSRFError
from .logging_config import get_logger

log = get_logger(__name__)


# ============ SSRF Protection ============


class SSRFProtector:
    """Protect against Server-Side Request Forgery attacks.

    Blocks requests to internal IPs, private networks, and dangerous protocols.
    """

    # Private/reserved IP ranges
    PRIVATE_NETWORKS = [
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
        ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ]

    # Dangerous protocols
    DANGEROUS_PROTOCOLS = {
        "file",
        "gopher",
        "dict",
        "ftp",
        "ldap",
        "ldaps",
        "tftp",
        "netdoc",
        "php",
        "expect",
        "ssh",
        "telnet",
    }

    # Allowed protocols
    ALLOWED_PROTOCOLS = {"http", "https"}

    def __init__(
        self,
        allowed_protocols: set[str] | None = None,
        block_private_ips: bool = True,
        block_localhost: bool = True,
        dns_resolution: bool = True,
        allowlist: set[str] | None = None,
        denylist: set[str] | None = None,
    ) -> None:
        self.allowed_protocols = allowed_protocols or self.ALLOWED_PROTOCOLS
        self.block_private_ips = block_private_ips
        self.block_localhost = block_localhost
        self.dns_resolution = dns_resolution
        self.allowlist = allowlist or set()
        self.denylist = denylist or set()

    def validate_url(self, url: str) -> tuple[bool, str]:
        """Validate a URL for SSRF safety.

        Args:
            url: URL to validate.

        Returns:
            Tuple of (is_safe, reason).
        """
        if not url or not isinstance(url, str):
            return False, "URL is empty or invalid"

        try:
            parsed = urlparse(url)
        except Exception as exc:
            return False, f"URL parsing failed: {exc}"

        # Check protocol
        protocol = parsed.scheme.lower()
        if protocol not in self.allowed_protocols:
            if protocol in self.DANGEROUS_PROTOCOLS:
                return False, f"Dangerous protocol blocked: {protocol}"
            return False, f"Protocol not allowed: {protocol}"

        # Check hostname
        hostname = parsed.hostname
        if not hostname:
            return False, "URL has no hostname"

        # Check denylist
        if hostname in self.denylist:
            return False, f"Hostname is denylisted: {hostname}"

        # Check allowlist (if configured)
        if self.allowlist and hostname not in self.allowlist:
            return False, f"Hostname is not in allowlist: {hostname}"

        # Check for localhost
        if self.block_localhost:
            if hostname.lower() in {"localhost", "localhost.localdomain", "ip6-localhost"}:
                return False, "Localhost access blocked"

        # DNS resolution and IP check
        if self.dns_resolution and self.block_private_ips:
            try:
                ip_addresses = socket.getaddrinfo(hostname, None)
                for family, _, _, _, sockaddr in ip_addresses:
                    ip = sockaddr[0]
                    if self._is_private_ip(ip):
                        return False, f"Resolved to private/internal IP: {ip}"
            except socket.gaierror:
                return False, f"DNS resolution failed for: {hostname}"

        return True, "URL is safe"

    def _is_private_ip(self, ip_str: str) -> bool:
        """Check if an IP address is private/reserved."""
        try:
            ip = ipaddress.ip_address(ip_str)
            for network in self.PRIVATE_NETWORKS:
                if ip in network:
                    return True
            return ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local
        except ValueError:
            return False

    def assert_safe_url(self, url: str) -> None:
        """Assert that a URL is safe, raising SSRFError if not.

        Args:
            url: URL to validate.

        Raises:
            SSRFError: If URL is not safe.
        """
        is_safe, reason = self.validate_url(url)
        if not is_safe:
            raise SSRFError(url=url, reason=reason)


# ============ Input Validation ============


class InputValidator:
    """Validate and sanitize user inputs.

    Provides validation for URLs, file paths, sizes, and content types.
    """

    # URL regex pattern
    URL_PATTERN = re.compile(
        r"^https?://"  # protocol
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain
        r"localhost|"  # localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # IP
        r"(?::\d+)?"  # port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )

    # Dangerous file path patterns
    PATH_TRAVERSAL_PATTERNS = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e%2f",
        r"%2e%2e/",
        r"\.\.%2f",
        r"\.\.%5c",
    ]

    def __init__(
        self,
        max_url_length: int = 2048,
        max_content_length: int = 50 * 1024 * 1024,  # 50MB
        max_filename_length: int = 255,
        allowed_file_extensions: set[str] | None = None,
    ) -> None:
        self.max_url_length = max_url_length
        self.max_content_length = max_content_length
        self.max_filename_length = max_filename_length
        self.allowed_file_extensions = allowed_file_extensions

    def validate_url(self, url: str) -> tuple[bool, str]:
        """Validate a URL format.

        Args:
            url: URL to validate.

        Returns:
            Tuple of (is_valid, reason).
        """
        if not url or not isinstance(url, str):
            return False, "URL is empty or not a string"

        if len(url) > self.max_url_length:
            return False, f"URL too long: {len(url)} > {self.max_url_length}"

        if not self.URL_PATTERN.match(url):
            return False, "URL format is invalid"

        return True, "URL is valid"

    def validate_file_path(self, path: str, base_dir: str = "") -> tuple[bool, str]:
        """Validate a file path for safety.

        Args:
            path: File path to validate.
            base_dir: Base directory to restrict access to.

        Returns:
            Tuple of (is_valid, reason).
        """
        if not path or not isinstance(path, str):
            return False, "Path is empty or not a string"

        if len(path) > self.max_filename_length:
            return False, f"Path too long: {len(path)} > {self.max_filename_length}"

        # Check for path traversal
        path_lower = path.lower()
        for pattern in self.PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, path_lower):
                return False, "Path traversal detected"

        # Check file extension
        if self.allowed_file_extensions:
            ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
            if ext and ext not in self.allowed_file_extensions:
                return False, f"File extension not allowed: {ext}"

        # Check if path is within base directory
        if base_dir:
            import os

            real_base = os.path.realpath(base_dir)
            real_path = os.path.realpath(os.path.join(base_dir, path))
            if not real_path.startswith(real_base):
                return False, "Path is outside base directory"

        return True, "File path is valid"

    def validate_content_size(self, content: bytes, max_size: int | None = None) -> tuple[bool, str]:
        """Validate content size.

        Args:
            content: Content bytes.
            max_size: Maximum allowed size (default: self.max_content_length).

        Returns:
            Tuple of (is_valid, reason).
        """
        max_size = max_size or self.max_content_length
        size = len(content) if content else 0

        if size > max_size:
            return False, f"Content too large: {size} > {max_size}"

        return True, "Content size is valid"

    def sanitize_string(self, text: str, max_length: int = 10000) -> str:
        """Sanitize a string by removing dangerous characters.

        Args:
            text: Input text.
            max_length: Maximum length.

        Returns:
            Sanitized string.
        """
        if not text:
            return ""

        # Remove null bytes and control characters (except newlines and tabs)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

        # Truncate to max length
        if len(text) > max_length:
            text = text[:max_length]

        return text

    def assert_valid_url(self, url: str) -> None:
        """Assert URL is valid, raising InputValidationError if not."""
        is_valid, reason = self.validate_url(url)
        if not is_valid:
            raise InputValidationError(field="url", message=reason, value=url)


# ============ Rate Limiting ============


class TokenBucket:
    """Token bucket rate limiter.

    Limits the rate of operations by consuming tokens from a bucket
    that refills at a constant rate.
    """

    def __init__(self, rate: float, capacity: int) -> None:
        """Initialize token bucket.

        Args:
            rate: Tokens added per second.
            capacity: Maximum tokens in bucket.
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_refill = time.time()

    def consume(self, tokens: int = 1) -> bool:
        """Consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume.

        Returns:
            True if tokens were consumed, False if not enough tokens.
        """
        self._refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

    @property
    def available_tokens(self) -> float:
        """Current number of available tokens."""
        self._refill()
        return self.tokens

    def wait_time(self, tokens: int = 1) -> float:
        """Time to wait before tokens are available (seconds)."""
        self._refill()
        if self.tokens >= tokens:
            return 0.0
        return (tokens - self.tokens) / self.rate


class RateLimiter:
    """Multi-key rate limiter using token buckets.

    Supports per-key rate limiting with configurable rates.
    """

    def __init__(
        self,
        default_rate: float = 10.0,
        default_capacity: int = 10,
        key_limits: dict[str, tuple[float, int]] | None = None,
    ) -> None:
        self.default_rate = default_rate
        self.default_capacity = default_capacity
        self.key_limits = key_limits or {}
        self._buckets: dict[str, TokenBucket] = {}

    def _get_bucket(self, key: str) -> TokenBucket:
        """Get or create a token bucket for a key."""
        if key not in self._buckets:
            rate, capacity = self.key_limits.get(key, (self.default_rate, self.default_capacity))
            self._buckets[key] = TokenBucket(rate, capacity)
        return self._buckets[key]

    def allow(self, key: str = "default", tokens: int = 1) -> bool:
        """Check if an operation is allowed.

        Args:
            key: Rate limit key.
            tokens: Tokens to consume.

        Returns:
            True if allowed, False if rate limited.
        """
        bucket = self._get_bucket(key)
        return bucket.consume(tokens)

    def assert_allowed(self, key: str = "default", tokens: int = 1, service: str = "") -> None:
        """Assert operation is allowed, raising RateLimitError if not.

        Args:
            key: Rate limit key.
            tokens: Tokens to consume.
            service: Service name for error message.

        Raises:
            RateLimitError: If rate limited.
        """
        if not self.allow(key, tokens):
            bucket = self._get_bucket(key)
            raise RateLimitError(
                service=service or key,
                limit=int(bucket.rate),
                retry_after=bucket.wait_time(tokens),
            )

    def get_stats(self, key: str = "default") -> dict[str, Any]:
        """Get rate limit stats for a key."""
        bucket = self._get_bucket(key)
        return {
            "available_tokens": bucket.available_tokens,
            "capacity": bucket.capacity,
            "rate": bucket.rate,
            "wait_time": bucket.wait_time(),
        }

    def reset(self, key: str | None = None) -> None:
        """Reset rate limiter for a key or all keys."""
        if key:
            if key in self._buckets:
                del self._buckets[key]
        else:
            self._buckets.clear()


# ============ Sensitive Data Filtering ============


class SensitiveDataFilter:
    """Filter sensitive data from text and logs.

    Detects and masks API keys, passwords, tokens, and other sensitive information.
    """

    # Patterns for sensitive data
    SENSITIVE_PATTERNS = {
        "api_key": re.compile(r'(?i)(?:api[_-]?key|apikey)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{6,})["\']?'),
        "password": re.compile(r'(?i)(?:password|passwd|pwd)\s*[:=]\s*["\']?([^\s"\']{6,})["\']?'),
        "token": re.compile(
            r'(?i)(?:token|auth[_-]?token|access[_-]?token|secret)\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{6,})["\']?'
        ),
        "bearer": re.compile(r"(?i)bearer\s+([a-zA-Z0-9_\-\.]{6,})"),
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
        "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
        "aws_secret": re.compile(r'(?i)aws[_-]?secret\s*[:=]\s*["\']?([A-Za-z0-9/+=]{40})["\']?'),
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
        "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    }

    def __init__(
        self,
        mask_char: str = "*",
        mask_length: int = 8,
        enabled_patterns: set[str] | None = None,
    ) -> None:
        self.mask_char = mask_char
        self.mask_length = mask_length
        self.enabled_patterns = enabled_patterns or set(self.SENSITIVE_PATTERNS.keys())

    def mask(self, text: str) -> str:
        """Mask sensitive data in text.

        Args:
            text: Input text.

        Returns:
            Text with sensitive data masked.
        """
        if not text:
            return text

        masked = text
        for pattern_name, pattern in self.SENSITIVE_PATTERNS.items():
            if pattern_name not in self.enabled_patterns:
                continue
            masked = pattern.sub(self._mask_match, masked)

        return masked

    def _mask_match(self, match: re.Match) -> str:
        """Mask a regex match."""
        if match.lastindex and match.group(1):
            # Mask the captured group
            original = match.group(1)
            masked = self.mask_char * min(self.mask_length, len(original))
            return match.group(0).replace(original, masked)
        else:
            # Mask the entire match
            return self.mask_char * self.mask_length

    def detect(self, text: str) -> list[dict[str, Any]]:
        """Detect sensitive data in text.

        Args:
            text: Input text.

        Returns:
            List of detected sensitive data entries.
        """
        detections = []
        if not text:
            return detections

        for pattern_name, pattern in self.SENSITIVE_PATTERNS.items():
            if pattern_name not in self.enabled_patterns:
                continue
            for match in pattern.finditer(text):
                detections.append(
                    {
                        "type": pattern_name,
                        "position": match.start(),
                        "length": len(match.group(0)),
                        "preview": match.group(0)[:10] + "..." if len(match.group(0)) > 10 else match.group(0),
                    }
                )

        return detections

    def assert_no_sensitive_data(self, text: str) -> None:
        """Assert text contains no sensitive data.

        Args:
            text: Text to check.

        Raises:
            SensitiveDataError: If sensitive data is detected.
        """
        detections = self.detect(text)
        if detections:
            raise SensitiveDataError(
                message=f"Detected {len(detections)} sensitive data patterns",
                details={"detections": detections},
            )


# ============ Security Headers ============


class SecurityHeaders:
    """Configure security headers for HTTP responses."""

    DEFAULT_HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }

    @classmethod
    def get_headers(cls, custom_headers: dict[str, str] | None = None) -> dict[str, str]:
        """Get security headers, optionally merged with custom headers.

        Args:
            custom_headers: Custom headers to add/override.

        Returns:
            Dictionary of security headers.
        """
        headers = dict(cls.DEFAULT_HEADERS)
        if custom_headers:
            headers.update(custom_headers)
        return headers


# ============ Main Security Manager ============


class SecurityManager:
    """Main security manager combining all security features.

    Provides a unified interface for SSRF protection, input validation,
    rate limiting, and sensitive data filtering.
    """

    def __init__(
        self,
        ssrf_protector: SSRFProtector | None = None,
        input_validator: InputValidator | None = None,
        rate_limiter: RateLimiter | None = None,
        sensitive_filter: SensitiveDataFilter | None = None,
    ) -> None:
        self.ssrf_protector = ssrf_protector or SSRFProtector()
        self.input_validator = input_validator or InputValidator()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.sensitive_filter = sensitive_filter or SensitiveDataFilter()

    def validate_request(self, url: str, client_key: str = "default") -> None:
        """Validate an incoming request comprehensively.

        Args:
            url: Request URL.
            client_key: Client identifier for rate limiting.

        Raises:
            SSRFError: If URL is unsafe.
            InputValidationError: If URL is invalid.
            RateLimitError: If rate limit exceeded.
        """
        # Rate limit check
        self.rate_limiter.assert_allowed(client_key, service="request")

        # Input validation
        self.input_validator.assert_valid_url(url)

        # SSRF protection
        self.ssrf_protector.assert_safe_url(url)

    def filter_output(self, text: str) -> str:
        """Filter sensitive data from output text.

        Args:
            text: Output text.

        Returns:
            Filtered text.
        """
        return self.sensitive_filter.mask(text)

    def get_security_headers(self) -> dict[str, str]:
        """Get security headers for HTTP responses."""
        return SecurityHeaders.get_headers()

    def get_stats(self) -> dict[str, Any]:
        """Get security statistics."""
        return {
            "ssrf_protection_enabled": True,
            "input_validation_enabled": True,
            "rate_limiting_enabled": True,
            "sensitive_data_filtering_enabled": True,
            "rate_limiter_stats": self.rate_limiter.get_stats(),
        }
