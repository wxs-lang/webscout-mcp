"""Configuration management for webscout-mcp.

Configuration priority (highest to lowest):
1. Environment variables (WEBSCOUT_*)
2. TOML config file (~/.config/webscout/config.toml)
3. Built-in defaults
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _default_cache_dir() -> Path:
    """Return the default cache directory."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "webscout"
    return Path.home() / ".cache" / "webscout"


def _default_config_path() -> Path:
    """Return the default config file path."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "webscout" / "config.toml"
    return Path.home() / ".config" / "webscout" / "config.toml"


@dataclass
class Config:
    """Runtime configuration for webscout-mcp.

    All values can be overridden via environment variables with the
    ``WEBSCOUT_`` prefix, or via a TOML config file.
    """

    # --- Cache ---
    cache_dir: Path = field(default_factory=_default_cache_dir)
    cache_ttl: int = 7200  # seconds, default 2h
    cache_max_size_mb: int = 512

    # --- HTTP / fetching ---
    request_timeout: float = 15.0
    max_retries: int = 3
    retry_backoff: float = 0.5  # seconds, exponential
    user_agent: str = "Mozilla/5.0 (compatible; webscout-mcp/0.3; +https://github.com/wxs-lang/webscout-mcp)"
    max_content_length: int = 5 * 1024 * 1024  # 5 MB

    # --- Proxy ---
    proxy_http: str = ""
    proxy_https: str = ""

    # --- Rate limiting (per domain) ---
    rate_limit_per_second: float = 2.0
    rate_limit_burst: int = 5

    # --- Search ---
    search_max_results: int = 10
    search_safe_search: bool = True
    search_backends: list[str] = field(default_factory=lambda: ["bing", "duckduckgo"])
    search_merge_backends: bool = False  # Merge results from all backends

    # --- Circuit Breaker ---
    search_circuit_failure_threshold: int = 5  # Consecutive failures before circuit opens
    search_circuit_recovery_time: int = 60  # Seconds before circuit half-opens

    # --- SerpAPI (optional stable backend) ---
    serpapi_api_key: str = ""  # SerpAPI API key (optional, enables stable API-based search)
    serpapi_engine: str = "google"  # Search engine: google, bing, duckduckgo, etc.
    serpapi_timeout: float = 30.0  # Request timeout in seconds

    # --- Crawler ---
    crawler_max_depth: int = 2
    crawler_max_pages: int = 20
    crawler_same_domain_only: bool = True
    crawler_concurrency: int = 5
    crawler_delay: float = 0.0  # Base delay between requests in seconds
    crawler_max_retries: int = 2  # Maximum retries per page
    respect_robots: bool = True

    # --- Extraction ---
    extract_output_format: str = "markdown"  # markdown | text | html

    # --- Logging ---
    log_level: str = "WARNING"
    log_json: bool = False

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load configuration from file, then override with environment variables.

        Args:
            config_path: Path to TOML config file. If None, uses the default
                path (~/.config/webscout/config.toml) if it exists.

        Returns:
            A Config instance with merged configuration.
        """
        # Start with defaults
        kwargs: dict[str, Any] = {}

        # Load from config file if it exists
        path = config_path or _default_config_path()
        if path.exists():
            file_config = cls._parse_toml(path)
            kwargs.update(file_config)

        # Override with environment variables
        env_config = cls._parse_env()
        kwargs.update(env_config)

        return cls(**kwargs)

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config instance, overriding defaults from environment.

        Also loads config file if it exists (env vars take priority).
        """
        return cls.load()

    @staticmethod
    def _parse_toml(path: Path) -> dict[str, Any]:
        """Parse a TOML config file and return a flat dict of config values."""
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                return {}

        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return {}

        result: dict[str, Any] = {}

        # Map TOML sections to config attributes
        section_map = {
            "cache": {
                "dir": ("cache_dir", lambda v: Path(v)),
                "ttl": ("cache_ttl", int),
                "max_size_mb": ("cache_max_size_mb", int),
            },
            "fetch": {
                "timeout": ("request_timeout", float),
                "max_retries": ("max_retries", int),
                "retry_backoff": ("retry_backoff", float),
                "user_agent": ("user_agent", str),
                "max_content_length": ("max_content_length", int),
            },
            "proxy": {
                "http": ("proxy_http", str),
                "https": ("proxy_https", str),
            },
            "rate_limit": {
                "per_second": ("rate_limit_per_second", float),
                "burst": ("rate_limit_burst", int),
            },
            "search": {
                "max_results": ("search_max_results", int),
                "safe_search": ("search_safe_search", bool),
                "backends": ("search_backends", lambda v: [str(x) for x in v]),
                "merge_backends": ("search_merge_backends", bool),
            },
            "crawler": {
                "max_depth": ("crawler_max_depth", int),
                "max_pages": ("crawler_max_pages", int),
                "same_domain_only": ("crawler_same_domain_only", bool),
                "concurrency": ("crawler_concurrency", int),
                "delay": ("crawler_delay", float),
                "max_retries": ("crawler_max_retries", int),
                "respect_robots": ("respect_robots", bool),
            },
            "extract": {
                "output_format": ("extract_output_format", str),
            },
            "logging": {
                "level": ("log_level", str),
                "json": ("log_json", bool),
            },
        }

        for section, keys in section_map.items():
            if section in data and isinstance(data[section], dict):
                for key, (attr, converter) in keys.items():
                    if key in data[section]:
                        try:
                            result[attr] = converter(data[section][key])
                        except (ValueError, TypeError):
                            pass

        return result

    @staticmethod
    def _parse_env() -> dict[str, Any]:
        """Parse environment variables and return a dict of config values."""
        result: dict[str, Any] = {}
        env_map = {
            "WEBSCOUT_CACHE_DIR": ("cache_dir", lambda v: Path(v)),
            "WEBSCOUT_CACHE_TTL": ("cache_ttl", int),
            "WEBSCOUT_CACHE_MAX_SIZE_MB": ("cache_max_size_mb", int),
            "WEBSCOUT_REQUEST_TIMEOUT": ("request_timeout", float),
            "WEBSCOUT_MAX_RETRIES": ("max_retries", int),
            "WEBSCOUT_USER_AGENT": ("user_agent", str),
            "WEBSCOUT_PROXY_HTTP": ("proxy_http", str),
            "WEBSCOUT_PROXY_HTTPS": ("proxy_https", str),
            "WEBSCOUT_RATE_LIMIT_PER_SECOND": ("rate_limit_per_second", float),
            "WEBSCOUT_SEARCH_MAX_RESULTS": ("search_max_results", int),
            "WEBSCOUT_SEARCH_BACKENDS": ("search_backends", lambda v: [x.strip() for x in v.split(",") if x.strip()]),
            "WEBSCOUT_SEARCH_MERGE_BACKENDS": ("search_merge_backends", lambda v: v.lower() in ("1", "true", "yes")),
            "WEBSCOUT_SEARCH_CIRCUIT_FAILURE_THRESHOLD": ("search_circuit_failure_threshold", int),
            "WEBSCOUT_SEARCH_CIRCUIT_RECOVERY_TIME": ("search_circuit_recovery_time", int),
            "SERPAPI_API_KEY": ("serpapi_api_key", str),
            "SERPAPI_ENGINE": ("serpapi_engine", str),
            "SERPAPI_TIMEOUT": ("serpapi_timeout", float),
            "WEBSCOUT_CRAWLER_MAX_DEPTH": ("crawler_max_depth", int),
            "WEBSCOUT_CRAWLER_MAX_PAGES": ("crawler_max_pages", int),
            "WEBSCOUT_CRAWLER_CONCURRENCY": ("crawler_concurrency", int),
            "WEBSCOUT_CRAWLER_DELAY": ("crawler_delay", float),
            "WEBSCOUT_CRAWLER_MAX_RETRIES": ("crawler_max_retries", int),
            "WEBSCOUT_RESPECT_ROBOTS": ("respect_robots", lambda v: v.lower() in ("1", "true", "yes")),
            "WEBSCOUT_EXTRACT_OUTPUT_FORMAT": ("extract_output_format", str),
            "WEBSCOUT_LOG_LEVEL": ("log_level", str),
            "WEBSCOUT_LOG_JSON": ("log_json", lambda v: v.lower() in ("1", "true", "yes")),
        }
        for env_key, (attr, converter) in env_map.items():
            raw = os.environ.get(env_key)
            if raw is not None:
                try:
                    result[attr] = converter(raw)
                except (ValueError, TypeError):
                    pass
        return result

    def ensure_dirs(self) -> None:
        """Create cache directory if it doesn't exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def reload(self, config_path: Path | None = None) -> Config:
        """Reload configuration from file and environment variables.

        This method updates the current Config instance in-place with new
        configuration values. Useful for hot-reloading configuration without
        restarting the application.

        Args:
            config_path: Path to TOML config file. If None, uses the default
                path (~/.config/webscout/config.toml) if it exists.

        Returns:
            Self (the updated Config instance).
        """
        # Start with defaults
        kwargs: dict[str, Any] = {}

        # Load from config file if it exists
        path = config_path or _default_config_path()
        if path.exists():
            file_config = self._parse_toml(path)
            kwargs.update(file_config)

        # Override with environment variables
        env_config = self._parse_env()
        kwargs.update(env_config)

        # Update current instance
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

        return self

    def to_dict(self) -> dict[str, Any]:
        """Convert configuration to a dictionary.

        Returns:
            Dictionary with all configuration values.
        """
        result = {}
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if isinstance(value, Path):
                result[field_name] = str(value)
            else:
                result[field_name] = value
        return result
