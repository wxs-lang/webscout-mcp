"""Unified exception hierarchy for webscout-mcp.

Provides a comprehensive, categorized exception system with
error codes, context, and consistent handling.

Exception Categories:
- WebScoutError (base)
  - ConfigurationError
  - NetworkError
    - ConnectionError
    - TimeoutError
    - SSLError
  - SearchError
  - FetchError
  - ParseError
  - ValidationError
  - AuthenticationError
  - RateLimitError
  - SecurityError
    - SSRFError
    - InputValidationError
  - PluginError
  - CacheError
  - StorageError
  - AIServiceError
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


class WebScoutError(Exception):
    """Base exception for all webscout-mcp errors.

    Attributes:
        code: Unique error code.
        message: Human-readable error message.
        details: Additional error context.
        timestamp: When the error occurred.
        retryable: Whether the operation can be retried.
    """

    code: str = "WS000"
    retryable: bool = False

    def __init__(
        self,
        message: str = "",
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        retryable: Optional[bool] = None,
    ) -> None:
        self.message = message or self.__class__.__doc__ or "An error occurred"
        if code:
            self.code = code
        if retryable is not None:
            self.retryable = retryable
        self.details = details or {}
        self.timestamp = datetime.utcnow().isoformat()
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for serialization."""
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "retryable": self.retryable,
        }

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# ============ Configuration Errors ============


class ConfigurationError(WebScoutError):
    """Invalid or missing configuration."""

    code = "WS100"
    retryable = False


class MissingConfigError(ConfigurationError):
    """Required configuration value is missing."""

    code = "WS101"

    def __init__(self, key: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Missing required configuration: {key}",
            details={"missing_key": key},
            **kwargs,
        )


class InvalidConfigError(ConfigurationError):
    """Configuration value is invalid."""

    code = "WS102"

    def __init__(self, key: str, value: Any, reason: str = "", **kwargs: Any) -> None:
        super().__init__(
            message=f"Invalid configuration for {key}: {value!r}. {reason}",
            details={"key": key, "value": value, "reason": reason},
            **kwargs,
        )


# ============ Network Errors ============


class NetworkError(WebScoutError):
    """Base class for network-related errors."""

    code = "WS200"
    retryable = True


class ConnectionError(NetworkError):
    """Failed to establish a connection."""

    code = "WS201"

    def __init__(self, url: str = "", reason: str = "", **kwargs: Any) -> None:
        super().__init__(
            message=f"Connection failed: {url or 'unknown'}. {reason}",
            details={"url": url, "reason": reason},
            **kwargs,
        )


class TimeoutError(NetworkError):
    """Operation timed out."""

    code = "WS202"

    def __init__(self, operation: str = "", timeout: float = 0, **kwargs: Any) -> None:
        super().__init__(
            message=f"Operation timed out: {operation or 'unknown'} (timeout: {timeout}s)",
            details={"operation": operation, "timeout": timeout},
            **kwargs,
        )


class SSLError(NetworkError):
    """SSL/TLS certificate or handshake error."""

    code = "WS203"
    retryable = False


class DNSResolutionError(NetworkError):
    """DNS resolution failed."""

    code = "WS204"

    def __init__(self, hostname: str = "", **kwargs: Any) -> None:
        super().__init__(
            message=f"DNS resolution failed for: {hostname or 'unknown'}",
            details={"hostname": hostname},
            **kwargs,
        )


class HTTPError(NetworkError):
    """HTTP error response."""

    code = "WS205"

    def __init__(
        self,
        status_code: int,
        url: str = "",
        reason: str = "",
        **kwargs: Any,
    ) -> None:
        self.status_code = status_code
        retryable = 500 <= status_code < 600 or status_code == 429
        super().__init__(
            message=f"HTTP {status_code}: {reason or 'Unknown error'} for {url}",
            details={"status_code": status_code, "url": url, "reason": reason},
            retryable=retryable,
            **kwargs,
        )


# ============ Search Errors ============


class SearchError(WebScoutError):
    """Base class for search-related errors."""

    code = "WS300"
    retryable = True


class SearchBackendError(SearchError):
    """Search backend failed."""

    code = "WS301"

    def __init__(self, backend: str = "", reason: str = "", **kwargs: Any) -> None:
        super().__init__(
            message=f"Search backend '{backend}' failed: {reason}",
            details={"backend": backend, "reason": reason},
            **kwargs,
        )


class NoResultsError(SearchError):
    """Search returned no results."""

    code = "WS302"
    retryable = False


# ============ Fetch Errors ============


class FetchError(WebScoutError):
    """Base class for content fetch errors."""

    code = "WS400"
    retryable = True


class ContentExtractionError(FetchError):
    """Failed to extract content from page."""

    code = "WS401"


class PageLoadError(FetchError):
    """Page failed to load."""

    code = "WS402"


# ============ Parse Errors ============


class ParseError(WebScoutError):
    """Base class for parsing errors."""

    code = "WS500"
    retryable = False


class HTMLParseError(ParseError):
    """Failed to parse HTML."""

    code = "WS501"


class JSONParseError(ParseError):
    """Failed to parse JSON."""

    code = "WS502"


class PDFParseError(ParseError):
    """Failed to parse PDF."""

    code = "WS503"


# ============ Validation Errors ============


class ValidationError(WebScoutError):
    """Input validation failed."""

    code = "WS600"
    retryable = False

    def __init__(
        self,
        field: str = "",
        message: str = "",
        value: Any = None,
        errors: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> None:
        self.field = field
        self.errors = errors or []
        super().__init__(
            message=message or f"Validation failed for field: {field}",
            details={"field": field, "value": value, "errors": self.errors},
            **kwargs,
        )


class InvalidURLError(ValidationError):
    """URL is invalid."""

    code = "WS601"

    def __init__(self, url: str = "", reason: str = "", **kwargs: Any) -> None:
        super().__init__(
            field="url",
            message=f"Invalid URL: {url}. {reason}",
            value=url,
            **kwargs,
        )


# ============ Authentication Errors ============


class AuthenticationError(WebScoutError):
    """Authentication failed."""

    code = "WS700"
    retryable = False


class InvalidTokenError(AuthenticationError):
    """API token is invalid or expired."""

    code = "WS701"


class PermissionDeniedError(AuthenticationError):
    """Insufficient permissions."""

    code = "WS702"


# ============ Rate Limit Errors ============


class RateLimitError(WebScoutError):
    """Rate limit exceeded."""

    code = "WS800"
    retryable = True

    def __init__(
        self,
        service: str = "",
        limit: int = 0,
        retry_after: float = 0,
        **kwargs: Any,
    ) -> None:
        self.retry_after = retry_after
        super().__init__(
            message=f"Rate limit exceeded for {service}: {limit} requests. Retry after {retry_after}s",
            details={"service": service, "limit": limit, "retry_after": retry_after},
            **kwargs,
        )


# ============ Security Errors ============


class SecurityError(WebScoutError):
    """Base class for security-related errors."""

    code = "WS900"
    retryable = False


class SSRFError(SecurityError):
    """Potential SSRF attack detected."""

    code = "WS901"

    def __init__(self, url: str = "", reason: str = "", **kwargs: Any) -> None:
        super().__init__(
            message=f"SSRF protection blocked URL: {url}. {reason}",
            details={"url": url, "reason": reason},
            **kwargs,
        )


class InputValidationError(SecurityError):
    """Input failed security validation."""

    code = "WS902"


class SensitiveDataError(SecurityError):
    """Sensitive data detected in output."""

    code = "WS903"


# ============ Plugin Errors ============


class PluginError(WebScoutError):
    """Base class for plugin errors."""

    code = "WSA00"


class PluginNotFoundError(PluginError):
    """Plugin not found."""

    code = "WSA01"

    def __init__(self, plugin_name: str = "", **kwargs: Any) -> None:
        super().__init__(
            message=f"Plugin not found: {plugin_name}",
            details={"plugin_name": plugin_name},
            **kwargs,
        )


class PluginLoadError(PluginError):
    """Failed to load plugin."""

    code = "WSA02"


# ============ Cache Errors ============


class CacheError(WebScoutError):
    """Base class for cache errors."""

    code = "WSB00"


class CacheMissError(CacheError):
    """Cache miss (not always an error)."""

    code = "WSB01"


# ============ Storage Errors ============


class StorageError(WebScoutError):
    """Base class for storage errors."""

    code = "WSC00"
    retryable = True


class DatabaseError(StorageError):
    """Database operation failed."""

    code = "WSC01"


class FileStorageError(StorageError):
    """File storage operation failed."""

    code = "WSC02"


# ============ AI Service Errors ============


class AIServiceError(WebScoutError):
    """Base class for AI service errors."""

    code = "WSD00"
    retryable = True


class ModelNotFoundError(AIServiceError):
    """AI model not found."""

    code = "WSD01"
    retryable = False


class HallucinationDetectedError(AIServiceError):
    """Potential hallucination detected in AI output."""

    code = "WSD02"
    retryable = False


class OutputValidationError(AIServiceError):
    """AI output failed validation."""

    code = "WSD03"
    retryable = True


# ============ Error Registry ============


class ErrorRegistry:
    """Registry for looking up error classes by code."""

    _registry: Dict[str, type] = {}

    @classmethod
    def register(cls, error_class: type) -> type:
        """Register an error class."""
        if hasattr(error_class, "code"):
            cls._registry[error_class.code] = error_class
        return error_class

    @classmethod
    def get_by_code(cls, code: str) -> Optional[type]:
        """Get error class by code."""
        return cls._registry.get(code)

    @classmethod
    def list_all(cls) -> Dict[str, str]:
        """List all registered error codes and names."""
        return {code: klass.__name__ for code, klass in cls._registry.items()}


# Register all error classes
def _register_all() -> None:
    for name, obj in list(globals().items()):
        if isinstance(obj, type) and issubclass(obj, WebScoutError) and obj != WebScoutError:
            ErrorRegistry.register(obj)


_register_all()


# ============ Error Handling Utilities ============


def safe_execute(
    func: callable,
    *args: Any,
    default: Any = None,
    catch: tuple = (Exception,),
    on_error: Optional[callable] = None,
    **kwargs: Any,
) -> Any:
    """Safely execute a function, returning default on error.

    Args:
        func: Function to execute.
        *args: Positional arguments.
        default: Default value to return on error.
        catch: Exception types to catch.
        on_error: Callback for error handling (exception) -> None.
        **kwargs: Keyword arguments.

    Returns:
        Function result or default value.
    """
    try:
        return func(*args, **kwargs)
    except catch as exc:
        if on_error:
            on_error(exc)
        return default


async def async_safe_execute(
    func: callable,
    *args: Any,
    default: Any = None,
    catch: tuple = (Exception,),
    on_error: Optional[callable] = None,
    **kwargs: Any,
) -> Any:
    """Safely execute an async function, returning default on error."""
    try:
        return await func(*args, **kwargs)
    except catch as exc:
        if on_error:
            on_error(exc)
        return default


def format_error(error: Exception, include_traceback: bool = False) -> str:
    """Format an exception into a readable string.

    Args:
        error: Exception instance.
        include_traceback: Whether to include traceback.

    Returns:
        Formatted error string.
    """
    if isinstance(error, WebScoutError):
        return str(error)

    return f"{type(error).__name__}: {str(error)}"


def get_error_context(error: Exception) -> Dict[str, Any]:
    """Extract context from an exception.

    Args:
        error: Exception instance.

    Returns:
        Dictionary with error context.
    """
    context = {
        "type": type(error).__name__,
        "message": str(error),
    }

    if isinstance(error, WebScoutError):
        context.update(error.to_dict())

    return context
