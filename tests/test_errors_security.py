"""Tests for unified errors and security modules."""

import time

import pytest

from webscout_mcp.errors import (
    ConfigurationError,
    ConnectionError,
    ErrorRegistry,
    HTTPError,
    InvalidConfigError,
    InvalidURLError,
    MissingConfigError,
    RateLimitError,
    SSRFError,
    TimeoutError,
    ValidationError,
    WebScoutError,
    format_error,
    get_error_context,
    safe_execute,
)
from webscout_mcp.security import (
    InputValidator,
    RateLimiter,
    SecurityHeaders,
    SecurityManager,
    SensitiveDataFilter,
    SSRFProtector,
    TokenBucket,
)

# ============ Error Tests ============


class TestWebScoutError:
    """Test base error class."""

    def test_creation(self):
        error = WebScoutError("Test error")
        assert error.message == "Test error"
        assert error.code == "WS000"
        assert error.retryable is False

    def test_to_dict(self):
        error = WebScoutError("Test", code="TEST001", details={"key": "value"})
        data = error.to_dict()
        assert data["code"] == "TEST001"
        assert data["message"] == "Test"
        assert data["details"]["key"] == "value"

    def test_str(self):
        error = WebScoutError("Test message", code="TEST001")
        assert "[TEST001]" in str(error)
        assert "Test message" in str(error)


class TestConfigurationErrors:
    """Test configuration error classes."""

    def test_missing_config(self):
        error = MissingConfigError("api_key")
        assert "api_key" in error.message
        assert error.details["missing_key"] == "api_key"

    def test_invalid_config(self):
        error = InvalidConfigError("timeout", -1, "must be positive")
        assert "timeout" in error.message
        assert error.details["value"] == -1


class TestNetworkErrors:
    """Test network error classes."""

    def test_connection_error(self):
        error = ConnectionError("https://example.com", "connection refused")
        assert "example.com" in error.message
        assert error.retryable is True

    def test_timeout_error(self):
        error = TimeoutError("fetch", 30.0)
        assert "fetch" in error.message
        assert error.details["timeout"] == 30.0

    def test_http_error_retryable(self):
        error = HTTPError(503, "https://example.com", "Service Unavailable")
        assert error.status_code == 503
        assert error.retryable is True

    def test_http_error_not_retryable(self):
        error = HTTPError(404, "https://example.com", "Not Found")
        assert error.retryable is False


class TestValidationErrors:
    """Test validation error classes."""

    def test_validation_error(self):
        error = ValidationError("email", "Invalid email format", "test")
        assert error.field == "email"
        assert "email" in error.message

    def test_invalid_url_error(self):
        error = InvalidURLError("not-a-url", "invalid format")
        assert "not-a-url" in error.message


class TestRateLimitError:
    """Test rate limit error."""

    def test_creation(self):
        error = RateLimitError("api", 100, 60.0)
        assert error.retry_after == 60.0
        assert "api" in error.message


class TestErrorRegistry:
    """Test error registry."""

    def test_get_by_code(self):
        error_class = ErrorRegistry.get_by_code("WS100")
        assert error_class == ConfigurationError

    def test_get_nonexistent(self):
        assert ErrorRegistry.get_by_code("NONEXISTENT") is None

    def test_list_all(self):
        all_errors = ErrorRegistry.list_all()
        assert "WS100" in all_errors
        assert "WS200" in all_errors


class TestErrorUtilities:
    """Test error handling utilities."""

    def test_safe_execute_success(self):
        result = safe_execute(lambda x: x * 2, 5, default=0)
        assert result == 10

    def test_safe_execute_error(self):
        def raise_error():
            raise ValueError("test")

        result = safe_execute(raise_error, default="fallback")
        assert result == "fallback"

    def test_safe_execute_on_error(self):
        errors = []

        def raise_error():
            raise ValueError("test")

        def on_error(exc):
            errors.append(str(exc))

        safe_execute(raise_error, default=None, on_error=on_error)
        assert len(errors) == 1

    def test_format_error_webscout(self):
        error = WebScoutError("test", code="TEST001")
        formatted = format_error(error)
        assert "TEST001" in formatted

    def test_format_error_standard(self):
        error = ValueError("test value error")
        formatted = format_error(error)
        assert "ValueError" in formatted

    def test_get_error_context(self):
        error = WebScoutError("test", code="TEST001")
        context = get_error_context(error)
        assert context["type"] == "WebScoutError"
        assert context["code"] == "TEST001"


# ============ Security Tests ============


class TestSSRFProtector:
    """Test SSRF protection."""

    def test_creation(self):
        protector = SSRFProtector()
        assert protector is not None

    def test_valid_http_url(self):
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("https://example.com")
        assert is_safe is True

    def test_dangerous_protocol(self):
        protector = SSRFProtector()
        is_safe, reason = protector.validate_url("file:///etc/passwd")
        assert is_safe is False
        assert "file" in reason.lower()

    def test_gopher_protocol(self):
        protector = SSRFProtector()
        is_safe, _ = protector.validate_url("gopher://localhost:25/")
        assert is_safe is False

    def test_localhost_blocked(self):
        protector = SSRFProtector(dns_resolution=False)
        is_safe, reason = protector.validate_url("http://localhost/admin")
        assert is_safe is False
        assert "localhost" in reason.lower()

    def test_empty_url(self):
        protector = SSRFProtector()
        is_safe, _ = protector.validate_url("")
        assert is_safe is False

    def test_denylist(self):
        protector = SSRFProtector(denylist={"evil.com"}, dns_resolution=False)
        is_safe, _ = protector.validate_url("https://evil.com")
        assert is_safe is False

    def test_allowlist(self):
        protector = SSRFProtector(allowlist={"safe.com"}, dns_resolution=False)
        is_safe, _ = protector.validate_url("https://safe.com")
        assert is_safe is True
        is_safe2, _ = protector.validate_url("https://other.com")
        assert is_safe2 is False

    def test_assert_safe_url_raises(self):
        protector = SSRFProtector(dns_resolution=False)
        with pytest.raises(SSRFError):
            protector.assert_safe_url("http://localhost")


class TestInputValidator:
    """Test input validation."""

    def test_creation(self):
        validator = InputValidator()
        assert validator is not None

    def test_valid_url(self):
        validator = InputValidator()
        is_valid, _ = validator.validate_url("https://example.com/path?query=1")
        assert is_valid is True

    def test_invalid_url(self):
        validator = InputValidator()
        is_valid, _ = validator.validate_url("not-a-url")
        assert is_valid is False

    def test_url_too_long(self):
        validator = InputValidator(max_url_length=10)
        is_valid, _ = validator.validate_url("https://example.com/very/long/path")
        assert is_valid is False

    def test_path_traversal(self):
        validator = InputValidator()
        is_valid, _ = validator.validate_file_path("../../../etc/passwd")
        assert is_valid is False

    def test_valid_file_path(self):
        validator = InputValidator()
        is_valid, _ = validator.validate_file_path("data/file.txt")
        assert is_valid is True

    def test_file_extension_allowed(self):
        validator = InputValidator(allowed_file_extensions={"txt", "pdf"})
        is_valid, _ = validator.validate_file_path("document.pdf")
        assert is_valid is True

    def test_file_extension_not_allowed(self):
        validator = InputValidator(allowed_file_extensions={"txt"})
        is_valid, _ = validator.validate_file_path("script.exe")
        assert is_valid is False

    def test_content_size_valid(self):
        validator = InputValidator()
        is_valid, _ = validator.validate_content_size(b"small content")
        assert is_valid is True

    def test_content_size_too_large(self):
        validator = InputValidator(max_content_length=10)
        is_valid, _ = validator.validate_content_size(b"x" * 100)
        assert is_valid is False

    def test_sanitize_string(self):
        validator = InputValidator()
        sanitized = validator.sanitize_string("Hello\x00World\x07!")
        assert "\x00" not in sanitized
        assert "\x07" not in sanitized

    def test_sanitize_string_truncate(self):
        validator = InputValidator()
        sanitized = validator.sanitize_string("A" * 100, max_length=10)
        assert len(sanitized) == 10

    def test_assert_valid_url_raises(self):
        validator = InputValidator()
        with pytest.raises(Exception):
            validator.assert_valid_url("invalid")


class TestTokenBucket:
    """Test token bucket rate limiter."""

    def test_creation(self):
        bucket = TokenBucket(rate=10, capacity=10)
        assert bucket.rate == 10
        assert bucket.capacity == 10

    def test_consume_success(self):
        bucket = TokenBucket(rate=100, capacity=10)
        assert bucket.consume(1) is True

    def test_consume_not_enough(self):
        bucket = TokenBucket(rate=0.1, capacity=1)
        bucket.consume(1)  # Consume the only token
        assert bucket.consume(1) is False

    def test_refill(self):
        bucket = TokenBucket(rate=100, capacity=10)
        bucket.consume(5)
        time.sleep(0.1)
        assert bucket.available_tokens > 5

    def test_wait_time(self):
        bucket = TokenBucket(rate=1, capacity=1)
        bucket.consume(1)
        wait = bucket.wait_time(1)
        assert wait > 0


class TestRateLimiter:
    """Test multi-key rate limiter."""

    def test_creation(self):
        limiter = RateLimiter(default_rate=10, default_capacity=10)
        assert limiter is not None

    def test_allow(self):
        limiter = RateLimiter(default_rate=100, default_capacity=10)
        assert limiter.allow("user1") is True

    def test_rate_limit(self):
        limiter = RateLimiter(default_rate=0.1, default_capacity=1)
        limiter.allow("user1")
        assert limiter.allow("user1") is False

    def test_different_keys(self):
        limiter = RateLimiter(default_rate=0.1, default_capacity=1)
        limiter.allow("user1")
        assert limiter.allow("user2") is True  # Different key, different bucket

    def test_assert_allowed_raises(self):
        limiter = RateLimiter(default_rate=0.1, default_capacity=1)
        limiter.allow("user1")
        with pytest.raises(RateLimitError):
            limiter.assert_allowed("user1", service="test")

    def test_get_stats(self):
        limiter = RateLimiter(default_rate=10, default_capacity=10)
        stats = limiter.get_stats("user1")
        assert "available_tokens" in stats
        assert "capacity" in stats

    def test_reset(self):
        limiter = RateLimiter(default_rate=0.1, default_capacity=1)
        limiter.allow("user1")
        limiter.reset("user1")
        assert limiter.allow("user1") is True


class TestSensitiveDataFilter:
    """Test sensitive data filtering."""

    def test_creation(self):
        filter_obj = SensitiveDataFilter()
        assert filter_obj is not None

    def test_mask_api_key(self):
        filter_obj = SensitiveDataFilter()
        text = "api_key=abcdefghijklmnopqrstuvwxyz123456"
        masked = filter_obj.mask(text)
        assert "abcdefghijklmnopqrstuvwxyz123456" not in masked

    def test_mask_password(self):
        filter_obj = SensitiveDataFilter()
        text = "password=mysecretpassword123"
        masked = filter_obj.mask(text)
        assert "mysecretpassword123" not in masked

    def test_mask_github_token(self):
        filter_obj = SensitiveDataFilter()
        text = "token: ghp_exampleFakeToken1234567890abcdefghijkl"
        masked = filter_obj.mask(text)
        assert "ghp_exampleFakeToken1234567890abcdefghijkl" not in masked

    def test_mask_email(self):
        filter_obj = SensitiveDataFilter()
        text = "Contact: test@example.com for info"
        masked = filter_obj.mask(text)
        assert "test@example.com" not in masked

    def test_detect(self):
        filter_obj = SensitiveDataFilter()
        text = "api_key=abcdefghijklmnopqrstuvwxyz123456"
        detections = filter_obj.detect(text)
        assert len(detections) > 0
        assert detections[0]["type"] == "api_key"

    def test_no_sensitive_data(self):
        filter_obj = SensitiveDataFilter()
        text = "This is a normal text with no sensitive data."
        detections = filter_obj.detect(text)
        assert len(detections) == 0

    def test_assert_no_sensitive_data_raises(self):
        filter_obj = SensitiveDataFilter()
        with pytest.raises(Exception):
            filter_obj.assert_no_sensitive_data("password=secret123")


class TestSecurityHeaders:
    """Test security headers."""

    def test_get_default_headers(self):
        headers = SecurityHeaders.get_headers()
        assert "X-Content-Type-Options" in headers
        assert "X-Frame-Options" in headers
        assert "Content-Security-Policy" in headers

    def test_custom_headers(self):
        headers = SecurityHeaders.get_headers({"X-Custom": "value"})
        assert headers["X-Custom"] == "value"
        assert "X-Content-Type-Options" in headers  # Defaults still present


class TestSecurityManager:
    """Test main security manager."""

    def test_creation(self):
        manager = SecurityManager()
        assert manager.ssrf_protector is not None
        assert manager.input_validator is not None
        assert manager.rate_limiter is not None
        assert manager.sensitive_filter is not None

    def test_filter_output(self):
        manager = SecurityManager()
        filtered = manager.filter_output("password=secret123")
        assert "secret123" not in filtered

    def test_get_security_headers(self):
        manager = SecurityManager()
        headers = manager.get_security_headers()
        assert len(headers) > 0

    def test_get_stats(self):
        manager = SecurityManager()
        stats = manager.get_stats()
        assert stats["ssrf_protection_enabled"] is True
        assert stats["input_validation_enabled"] is True
