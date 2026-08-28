"""
Tests for errors module - all exception classes, ErrorRegistry, and safe_execute.

Tests exception inheritance, message handling, attributes, serialization,
error registry functionality, and safe execution utility.
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webscout_mcp.errors import (
    WebScoutError,
    ConfigurationError,
    MissingConfigError,
    InvalidConfigError,
    NetworkError,
    ConnectionError,
    TimeoutError,
    SSLError,
    DNSResolutionError,
    HTTPError,
    SearchError,
    SearchBackendError,
    NoResultsError,
    FetchError,
    ContentExtractionError,
    PageLoadError,
    ParseError,
    HTMLParseError,
    JSONParseError,
    PDFParseError,
    ValidationError,
    InvalidURLError,
    AuthenticationError,
    InvalidTokenError,
    PermissionDeniedError,
    RateLimitError,
    SecurityError,
    SSRFError,
    InputValidationError,
    SensitiveDataError,
    PluginError,
    PluginNotFoundError,
    PluginLoadError,
    CacheError,
    CacheMissError,
    StorageError,
    DatabaseError,
    FileStorageError,
    AIServiceError,
    ModelNotFoundError,
    HallucinationDetectedError,
    OutputValidationError,
    ErrorRegistry,
    safe_execute,
)


class TestWebScoutErrorBase:
    """Tests for WebScoutError base class."""

    def test_default_creation(self):
        """Test default error creation."""
        err = WebScoutError()
        assert err.code == "WS000"
        assert err.retryable is False
        assert err.details == {}
        assert err.timestamp is not None
        assert err.message is not None

    def test_custom_message(self):
        """Test error with custom message."""
        err = WebScoutError("Something went wrong")
        assert err.message == "Something went wrong"
        assert str(err) == "[WS000] Something went wrong"

    def test_custom_code(self):
        """Test error with custom code."""
        err = WebScoutError("Test error", code="CUSTOM001")
        assert err.code == "CUSTOM001"
        assert str(err) == "[CUSTOM001] Test error"

    def test_custom_details(self):
        """Test error with custom details."""
        details = {"url": "https://example.com", "status_code": 500}
        err = WebScoutError("Request failed", details=details)
        assert err.details == details
        assert err.details["url"] == "https://example.com"

    def test_retryable_true(self):
        """Test error with retryable=True."""
        err = WebScoutError("Transient error", retryable=True)
        assert err.retryable is True

    def test_to_dict(self):
        """Test error to_dict serialization."""
        err = WebScoutError("Test error", code="TEST001", details={"key": "value"})
        data = err.to_dict()
        assert data["error"] == "WebScoutError"
        assert data["code"] == "TEST001"
        assert data["message"] == "Test error"
        assert data["details"] == {"key": "value"}
        assert "timestamp" in data
        assert data["retryable"] is False

    def test_str_representation(self):
        """Test error string representation."""
        err = WebScoutError("Test message", code="TEST001")
        assert str(err) == "[TEST001] Test message"

    def test_repr_representation(self):
        """Test error repr representation."""
        err = WebScoutError("Test message", code="TEST001")
        repr_str = repr(err)
        assert "WebScoutError" in repr_str
        assert "TEST001" in repr_str
        assert "Test message" in repr_str

    def test_exception_inheritance(self):
        """Test WebScoutError inherits from Exception."""
        assert issubclass(WebScoutError, Exception)

    def test_can_be_raised(self):
        """Test error can be raised and caught."""
        with pytest.raises(WebScoutError) as exc_info:
            raise WebScoutError("Raised error")
        assert exc_info.value.message == "Raised error"

    def test_timestamp_is_iso_format(self):
        """Test timestamp is in ISO format."""
        err = WebScoutError()
        assert "T" in err.timestamp


class TestConfigurationErrors:
    """Tests for configuration error classes."""

    def test_configuration_error_inheritance(self):
        """Test ConfigurationError inherits from WebScoutError."""
        assert issubclass(ConfigurationError, WebScoutError)

    def test_missing_config_error_inheritance(self):
        """Test MissingConfigError inherits from ConfigurationError."""
        assert issubclass(MissingConfigError, ConfigurationError)

    def test_invalid_config_error_inheritance(self):
        """Test InvalidConfigError inherits from ConfigurationError."""
        assert issubclass(InvalidConfigError, ConfigurationError)

    def test_configuration_error_creation(self):
        """Test ConfigurationError creation."""
        err = ConfigurationError("Bad config")
        assert isinstance(err, WebScoutError)
        assert err.message == "Bad config"

    def test_missing_config_error_creation(self):
        """Test MissingConfigError creation with specific params."""
        err = MissingConfigError("API_KEY")
        assert isinstance(err, ConfigurationError)
        assert "API_KEY" in err.message
        assert err.details["missing_key"] == "API_KEY"

    def test_invalid_config_error_creation(self):
        """Test InvalidConfigError creation with specific params."""
        err = InvalidConfigError("port", -1, "Port must be positive")
        assert isinstance(err, ConfigurationError)
        assert "port" in err.message
        assert err.details["key"] == "port"
        assert err.details["value"] == -1


class TestNetworkErrors:
    """Tests for network error classes."""

    def test_network_error_inheritance(self):
        """Test NetworkError inherits from WebScoutError."""
        assert issubclass(NetworkError, WebScoutError)

    def test_connection_error_inheritance(self):
        """Test ConnectionError inherits from NetworkError."""
        assert issubclass(ConnectionError, NetworkError)

    def test_timeout_error_inheritance(self):
        """Test TimeoutError inherits from NetworkError."""
        assert issubclass(TimeoutError, NetworkError)

    def test_ssl_error_inheritance(self):
        """Test SSLError inherits from NetworkError."""
        assert issubclass(SSLError, NetworkError)

    def test_dns_resolution_error_inheritance(self):
        """Test DNSResolutionError inherits from NetworkError."""
        assert issubclass(DNSResolutionError, NetworkError)

    def test_http_error_inheritance(self):
        """Test HTTPError inherits from NetworkError."""
        assert issubclass(HTTPError, NetworkError)

    def test_network_error_retryable(self):
        """Test network errors can be retryable."""
        err = NetworkError("Network issue", retryable=True)
        assert err.retryable is True

    def test_timeout_error_creation(self):
        """Test TimeoutError creation."""
        err = TimeoutError("Request timed out after 30s")
        assert isinstance(err, NetworkError)
        assert "timed out" in err.message

    def test_http_error_creation(self):
        """Test HTTPError creation with specific params."""
        err = HTTPError(404, "https://example.com", "Not Found")
        assert isinstance(err, NetworkError)
        assert err.status_code == 404
        assert "404" in err.message
        assert err.details["status_code"] == 404
        assert err.details["url"] == "https://example.com"

    def test_http_error_500_is_retryable(self):
        """Test HTTP 500 error is retryable."""
        err = HTTPError(500, "https://example.com", "Server Error")
        assert err.retryable is True

    def test_http_error_429_is_retryable(self):
        """Test HTTP 429 error is retryable."""
        err = HTTPError(429, "https://example.com", "Too Many Requests")
        assert err.retryable is True

    def test_http_error_404_not_retryable(self):
        """Test HTTP 404 error is not retryable."""
        err = HTTPError(404, "https://example.com", "Not Found")
        assert err.retryable is False


class TestSearchErrors:
    """Tests for search error classes."""

    def test_search_error_inheritance(self):
        """Test SearchError inherits from WebScoutError."""
        assert issubclass(SearchError, WebScoutError)

    def test_search_backend_error_inheritance(self):
        """Test SearchBackendError inherits from SearchError."""
        assert issubclass(SearchBackendError, SearchError)

    def test_no_results_error_inheritance(self):
        """Test NoResultsError inherits from SearchError."""
        assert issubclass(NoResultsError, SearchError)

    def test_search_error_creation(self):
        """Test SearchError creation."""
        err = SearchError("Search failed")
        assert isinstance(err, WebScoutError)
        assert err.message == "Search failed"

    def test_no_results_error_creation(self):
        """Test NoResultsError creation."""
        err = NoResultsError("No results found for query")
        assert isinstance(err, SearchError)
        assert "No results" in err.message


class TestFetchErrors:
    """Tests for fetch error classes."""

    def test_fetch_error_inheritance(self):
        """Test FetchError inherits from WebScoutError."""
        assert issubclass(FetchError, WebScoutError)

    def test_content_extraction_error_inheritance(self):
        """Test ContentExtractionError inherits from FetchError."""
        assert issubclass(ContentExtractionError, FetchError)

    def test_page_load_error_inheritance(self):
        """Test PageLoadError inherits from FetchError."""
        assert issubclass(PageLoadError, FetchError)

    def test_fetch_error_creation(self):
        """Test FetchError creation."""
        err = FetchError("Failed to fetch page")
        assert isinstance(err, WebScoutError)
        assert err.message == "Failed to fetch page"


class TestParseErrors:
    """Tests for parse error classes."""

    def test_parse_error_inheritance(self):
        """Test ParseError inherits from WebScoutError."""
        assert issubclass(ParseError, WebScoutError)

    def test_html_parse_error_inheritance(self):
        """Test HTMLParseError inherits from ParseError."""
        assert issubclass(HTMLParseError, ParseError)

    def test_json_parse_error_inheritance(self):
        """Test JSONParseError inherits from ParseError."""
        assert issubclass(JSONParseError, ParseError)

    def test_pdf_parse_error_inheritance(self):
        """Test PDFParseError inherits from ParseError."""
        assert issubclass(PDFParseError, ParseError)

    def test_json_parse_error_creation(self):
        """Test JSONParseError creation."""
        err = JSONParseError("Invalid JSON syntax")
        assert isinstance(err, ParseError)
        assert "Invalid JSON" in err.message


class TestValidationErrors:
    """Tests for validation error classes."""

    def test_validation_error_inheritance(self):
        """Test ValidationError inherits from WebScoutError."""
        assert issubclass(ValidationError, WebScoutError)

    def test_invalid_url_error_inheritance(self):
        """Test InvalidURLError inherits from ValidationError."""
        assert issubclass(InvalidURLError, ValidationError)

    def test_validation_error_creation(self):
        """Test ValidationError creation."""
        # With custom message
        err = ValidationError("field_name", "Custom validation message")
        assert isinstance(err, WebScoutError)
        assert err.field == "field_name"
        assert err.message == "Custom validation message"
        assert err.details["field"] == "field_name"

    def test_validation_error_default_message(self):
        """Test ValidationError with default message."""
        err = ValidationError("email")
        assert "email" in err.message
        assert "Validation failed" in err.message


class TestAuthenticationErrors:
    """Tests for authentication error classes."""

    def test_authentication_error_inheritance(self):
        """Test AuthenticationError inherits from WebScoutError."""
        assert issubclass(AuthenticationError, WebScoutError)

    def test_invalid_token_error_inheritance(self):
        """Test InvalidTokenError inherits from AuthenticationError."""
        assert issubclass(InvalidTokenError, AuthenticationError)

    def test_permission_denied_error_inheritance(self):
        """Test PermissionDeniedError inherits from AuthenticationError."""
        assert issubclass(PermissionDeniedError, AuthenticationError)

    def test_invalid_token_error_creation(self):
        """Test InvalidTokenError creation."""
        err = InvalidTokenError("API token has expired")
        assert isinstance(err, AuthenticationError)
        assert "expired" in err.message


class TestSecurityErrors:
    """Tests for security error classes."""

    def test_security_error_inheritance(self):
        """Test SecurityError inherits from WebScoutError."""
        assert issubclass(SecurityError, WebScoutError)

    def test_ssrf_error_inheritance(self):
        """Test SSRFError inherits from SecurityError."""
        assert issubclass(SSRFError, SecurityError)

    def test_input_validation_error_inheritance(self):
        """Test InputValidationError inherits from SecurityError."""
        assert issubclass(InputValidationError, SecurityError)

    def test_sensitive_data_error_inheritance(self):
        """Test SensitiveDataError inherits from SecurityError."""
        assert issubclass(SensitiveDataError, SecurityError)

    def test_ssrf_error_creation(self):
        """Test SSRFError creation with specific params."""
        err = SSRFError("http://127.0.0.1", "Blocked request to localhost")
        assert isinstance(err, SecurityError)
        assert "localhost" in err.message or "127.0.0.1" in err.message


class TestPluginErrors:
    """Tests for plugin error classes."""

    def test_plugin_error_inheritance(self):
        """Test PluginError inherits from WebScoutError."""
        assert issubclass(PluginError, WebScoutError)

    def test_plugin_not_found_error_inheritance(self):
        """Test PluginNotFoundError inherits from PluginError."""
        assert issubclass(PluginNotFoundError, PluginError)

    def test_plugin_load_error_inheritance(self):
        """Test PluginLoadError inherits from PluginError."""
        assert issubclass(PluginLoadError, PluginError)

    def test_plugin_not_found_error_creation(self):
        """Test PluginNotFoundError creation with specific params."""
        err = PluginNotFoundError("my_plugin")
        assert isinstance(err, PluginError)
        assert "my_plugin" in err.message


class TestCacheErrors:
    """Tests for cache error classes."""

    def test_cache_error_inheritance(self):
        """Test CacheError inherits from WebScoutError."""
        assert issubclass(CacheError, WebScoutError)

    def test_cache_miss_error_inheritance(self):
        """Test CacheMissError inherits from CacheError."""
        assert issubclass(CacheMissError, CacheError)

    def test_cache_error_creation(self):
        """Test CacheError creation."""
        err = CacheError("Cache operation failed")
        assert isinstance(err, WebScoutError)
        assert err.message == "Cache operation failed"


class TestStorageErrors:
    """Tests for storage error classes."""

    def test_storage_error_inheritance(self):
        """Test StorageError inherits from WebScoutError."""
        assert issubclass(StorageError, WebScoutError)

    def test_database_error_inheritance(self):
        """Test DatabaseError inherits from StorageError."""
        assert issubclass(DatabaseError, StorageError)

    def test_file_storage_error_inheritance(self):
        """Test FileStorageError inherits from StorageError."""
        assert issubclass(FileStorageError, StorageError)

    def test_database_error_creation(self):
        """Test DatabaseError creation."""
        err = DatabaseError("Database connection failed")
        assert isinstance(err, StorageError)
        assert "Database" in err.message


class TestAIServiceErrors:
    """Tests for AI service error classes."""

    def test_ai_service_error_inheritance(self):
        """Test AIServiceError inherits from WebScoutError."""
        assert issubclass(AIServiceError, WebScoutError)

    def test_model_not_found_error_inheritance(self):
        """Test ModelNotFoundError inherits from AIServiceError."""
        assert issubclass(ModelNotFoundError, AIServiceError)

    def test_hallucination_detected_error_inheritance(self):
        """Test HallucinationDetectedError inherits from AIServiceError."""
        assert issubclass(HallucinationDetectedError, AIServiceError)

    def test_output_validation_error_inheritance(self):
        """Test OutputValidationError inherits from AIServiceError."""
        assert issubclass(OutputValidationError, AIServiceError)

    def test_model_not_found_error_creation(self):
        """Test ModelNotFoundError creation with specific params."""
        err = ModelNotFoundError("gpt-4")
        assert isinstance(err, AIServiceError)
        assert "gpt-4" in err.message


class TestRateLimitError:
    """Tests for RateLimitError class."""

    def test_rate_limit_error_inheritance(self):
        """Test RateLimitError inherits from WebScoutError."""
        assert issubclass(RateLimitError, WebScoutError)

    def test_rate_limit_error_creation(self):
        """Test RateLimitError creation with specific params."""
        err = RateLimitError("api_service", 100, 60)
        assert isinstance(err, WebScoutError)
        assert err.retry_after == 60
        assert err.retryable is True
        assert err.details["service"] == "api_service"
        assert err.details["limit"] == 100
        assert err.details["retry_after"] == 60


class TestErrorRegistry:
    """Tests for ErrorRegistry class."""

    def test_error_registry_has_registered_errors(self):
        """Test ErrorRegistry has registered errors after module load."""
        all_errors = ErrorRegistry.list_all()
        assert len(all_errors) > 0
        # Should have some known error codes (WS000 base class is excluded from registration)
        assert "WS101" in all_errors  # MissingConfigError
        assert "WS102" in all_errors  # InvalidConfigError
        assert "WS200" in all_errors  # NetworkError

    def test_error_registry_get_by_code(self):
        """Test getting error class by code."""
        error_class = ErrorRegistry.get_by_code("WS101")
        assert error_class is MissingConfigError

    def test_error_registry_get_by_code_nonexistent(self):
        """Test getting nonexistent error code returns None."""
        result = ErrorRegistry.get_by_code("NONEXISTENT")
        assert result is None

    def test_error_registry_list_all_returns_dict(self):
        """Test list_all returns dictionary."""
        all_errors = ErrorRegistry.list_all()
        assert isinstance(all_errors, dict)
        for code, name in all_errors.items():
            assert isinstance(code, str)
            assert isinstance(name, str)

    def test_error_registry_register_new_error(self):
        """Test registering a new error class."""

        class TestCustomError(WebScoutError):
            code = "TEST_CUSTOM_001"

        ErrorRegistry.register(TestCustomError)
        retrieved = ErrorRegistry.get_by_code("TEST_CUSTOM_001")
        assert retrieved is TestCustomError


class TestSafeExecute:
    """Tests for safe_execute utility function."""

    def test_safe_execute_success(self):
        """Test safe_execute with successful function."""
        result = safe_execute(lambda x: x * 2, 5)
        assert result == 10

    def test_safe_execute_with_default(self):
        """Test safe_execute returns default on error."""
        def failing_func():
            raise ValueError("Test error")

        result = safe_execute(failing_func, default="fallback")
        assert result == "fallback"

    def test_safe_execute_with_args(self):
        """Test safe_execute with positional arguments."""
        def add(a, b):
            return a + b

        result = safe_execute(add, 3, 4)
        assert result == 7

    def test_safe_execute_with_kwargs(self):
        """Test safe_execute with keyword arguments."""
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = safe_execute(greet, "World", greeting="Hi")
        assert result == "Hi, World!"

    def test_safe_execute_on_error_callback(self):
        """Test safe_execute calls on_error callback."""
        errors_caught = []

        def failing_func():
            raise RuntimeError("Test error")

        def on_error(exc):
            errors_caught.append(exc)

        safe_execute(failing_func, default=None, on_error=on_error)
        assert len(errors_caught) == 1
        assert isinstance(errors_caught[0], RuntimeError)

    def test_safe_execute_catch_specific_exception(self):
        """Test safe_execute catches only specified exceptions."""
        def value_error_func():
            raise ValueError("Value error")

        # Should catch ValueError
        result = safe_execute(value_error_func, default="caught", catch=(ValueError,))
        assert result == "caught"

    def test_safe_execute_propagates_uncatched_exception(self):
        """Test safe_execute propagates exceptions not in catch tuple."""
        def type_error_func():
            raise TypeError("Type error")

        # Should propagate TypeError because only ValueError is caught
        with pytest.raises(TypeError):
            safe_execute(type_error_func, default="caught", catch=(ValueError,))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
