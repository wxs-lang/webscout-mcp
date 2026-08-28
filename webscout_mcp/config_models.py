"""Pydantic-based configuration models for webscout-mcp.

Type-safe configuration with validation, environment variable support,
and automatic documentation generation.

Features:
- Type-safe configuration models
- Environment variable validation
- Nested configuration sections
- Default values with documentation
- Configuration validation rules
- Serialization to/from dict/JSON/TOML
- Hot-reload support
"""

from __future__ import annotations

import os
from typing import Literal, Optional

from .logging import get_logger

log = get_logger(__name__)

try:
    from pydantic import BaseModel, Field, field_validator, model_validator

    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    # Fallback: simple dataclass-based config
    from dataclasses import dataclass
    from dataclasses import field as dc_field

    class BaseModel:  # type: ignore
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def model_dump(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

        @classmethod
        def model_validate(cls, data):
            return cls(**data)

    def Field(default=None, **kwargs):  # type: ignore
        return default

    def field_validator(*args, **kwargs):  # type: ignore
        def decorator(func):
            return func

        return decorator

    def model_validator(*args, **kwargs):  # type: ignore
        def decorator(func):
            return func

        return decorator


class ServerConfig(BaseModel):
    """MCP server configuration."""

    host: str = Field(default="127.0.0.1", description="Server host address")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    workers: int = Field(default=1, ge=1, le=16, description="Number of worker processes")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Logging level"
    )
    request_timeout: float = Field(default=30.0, gt=0, description="Request timeout in seconds")
    max_request_size: int = Field(default=10 * 1024 * 1024, gt=0, description="Max request size in bytes")


class CacheConfig(BaseModel):
    """Caching configuration."""

    enabled: bool = Field(default=True, description="Enable caching")
    ttl: int = Field(default=3600, ge=0, description="Cache TTL in seconds")
    max_size: int = Field(default=1000, ge=0, description="Max number of cached items")
    backend: Literal["memory", "sqlite", "redis"] = Field(default="sqlite", description="Cache backend")
    sqlite_path: str = Field(default="~/.cache/webscout/cache.db", description="SQLite cache path")
    redis_url: Optional[str] = Field(default=None, description="Redis connection URL")
    eviction_policy: Literal["LRU", "LFU", "FIFO"] = Field(default="LRU", description="Cache eviction policy")


class SearchConfig(BaseModel):
    """Search configuration."""

    default_backend: Literal["bing", "duckduckgo", "google", "brave"] = Field(
        default="bing", description="Default search backend"
    )
    max_results: int = Field(default=10, ge=1, le=100, description="Max search results")
    request_timeout: float = Field(default=15.0, gt=0, description="Search request timeout")
    retry_count: int = Field(default=3, ge=0, le=10, description="Number of retries on failure")
    retry_delay: float = Field(default=1.0, ge=0, description="Delay between retries in seconds")
    user_agent: str = Field(
        default="Mozilla/5.0 (compatible; webscout-mcp/1.0)",
        description="User-Agent string for search requests",
    )
    enable_result_dedup: bool = Field(default=True, description="Enable result deduplication")
    merge_results: bool = Field(default=True, description="Merge results from multiple backends")


class CrawlerConfig(BaseModel):
    """Web crawler configuration."""

    max_depth: int = Field(default=2, ge=0, le=10, description="Max crawl depth")
    max_pages: int = Field(default=50, ge=1, le=10000, description="Max pages to crawl")
    concurrency: int = Field(default=5, ge=1, le=50, description="Number of concurrent requests")
    request_delay: float = Field(default=0.5, ge=0, description="Delay between requests in seconds")
    respect_robots_txt: bool = Field(default=True, description="Respect robots.txt rules")
    follow_redirects: bool = Field(default=True, description="Follow HTTP redirects")
    max_redirects: int = Field(default=5, ge=0, le=20, description="Max number of redirects")
    timeout: float = Field(default=30.0, gt=0, description="Request timeout in seconds")
    user_agent: str = Field(
        default="Mozilla/5.0 (compatible; webscout-mcp/1.0)",
        description="User-Agent string for crawler",
    )
    allowed_domains: list[str] = Field(default_factory=list, description="Allowed domains (empty = all)")
    denied_domains: list[str] = Field(default_factory=list, description="Denied domains")
    url_patterns: list[str] = Field(default_factory=list, description="URL regex patterns to include")
    save_html: bool = Field(default=False, description="Save raw HTML content")
    incremental: bool = Field(default=True, description="Enable incremental crawling via ETag/Last-Modified")


class AIConfig(BaseModel):
    """AI content understanding configuration."""

    backend: Literal["ollama", "openai", "doubao", "custom"] = Field(default="ollama", description="AI backend")
    model: str = Field(default="qwen2.5:7b", description="Model name")
    api_key: Optional[str] = Field(default=None, description="API key (for OpenAI/Doubao)")
    base_url: Optional[str] = Field(default=None, description="Custom API base URL")
    temperature: float = Field(default=0.7, ge=0, le=2, description="Sampling temperature")
    max_tokens: int = Field(default=2000, ge=1, le=32000, description="Max output tokens")
    top_p: float = Field(default=0.9, ge=0, le=1, description="Top-p sampling parameter")
    request_timeout: float = Field(default=60.0, gt=0, description="AI request timeout")
    max_retries: int = Field(default=3, ge=0, le=10, description="Max retries on failure")
    ollama_host: str = Field(default="http://localhost:11434", description="Ollama server host")


class VectorStoreConfig(BaseModel):
    """Vector store and RAG configuration."""

    enabled: bool = Field(default=True, description="Enable vector store")
    vector_db: Literal["chroma", "faiss", "milvus"] = Field(default="chroma", description="Vector database backend")
    embedding_backend: Literal["local", "openai", "custom"] = Field(
        default="local", description="Embedding model backend"
    )
    embedding_model: str = Field(default="BAAI/bge-small-zh-v1.5", description="Embedding model name")
    embedding_dimension: int = Field(default=384, ge=64, le=4096, description="Embedding dimension")
    persist_directory: str = Field(
        default="~/.local/share/webscout/vector_store", description="Vector store persistence directory"
    )
    collection_name: str = Field(default="webscout_docs", description="Default collection name")
    chunk_size: int = Field(default=1000, ge=100, le=10000, description="Text chunk size in characters")
    chunk_overlap: int = Field(default=200, ge=0, le=2000, description="Chunk overlap in characters")
    similarity_threshold: float = Field(default=0.7, ge=0, le=1, description="Minimum similarity score")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of results to retrieve")
    hybrid_search: bool = Field(default=True, description="Enable hybrid search (BM25 + semantic)")


class BrowserConfig(BaseModel):
    """Headless browser configuration."""

    enabled: bool = Field(default=True, description="Enable browser automation")
    browser_type: Literal["chromium", "firefox", "webkit"] = Field(default="chromium", description="Browser type")
    headless: bool = Field(default=True, description="Run in headless mode")
    block_media: bool = Field(default=True, description="Block images/media/CSS/fonts")
    block_images: bool = Field(default=True, description="Block image loading")
    block_stylesheets: bool = Field(default=True, description="Block CSS loading")
    block_fonts: bool = Field(default=True, description="Block font loading")
    timeout: float = Field(default=30.0, gt=0, description="Page load timeout in seconds")
    navigation_timeout: float = Field(default=30.0, gt=0, description="Navigation timeout")
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = Field(
        default="domcontentloaded", description="Wait until event for navigation"
    )
    stealth_mode: bool = Field(default=True, description="Enable anti-detection stealth mode")
    user_agent: Optional[str] = Field(default=None, description="Custom User-Agent (None = random)")
    viewport_width: int = Field(default=1920, ge=320, le=4096, description="Viewport width")
    viewport_height: int = Field(default=1080, ge=240, le=2160, description="Viewport height")
    proxy: Optional[str] = Field(default=None, description="Proxy URL (http://user:pass@host:port)")
    ignore_https_errors: bool = Field(default=False, description="Ignore HTTPS certificate errors")
    max_concurrent_pages: int = Field(default=3, ge=1, le=20, description="Max concurrent browser pages")


class MonitorConfig(BaseModel):
    """Web monitoring configuration."""

    check_interval: int = Field(default=300, ge=10, description="Check interval in seconds")
    min_change_size: int = Field(default=10, ge=0, description="Minimum change size to trigger alert")
    similarity_threshold: float = Field(default=0.95, ge=0, le=1, description="Content similarity threshold")
    history_limit: int = Field(default=100, ge=1, le=10000, description="Max history entries per URL")
    enable_diff: bool = Field(default=True, description="Generate diff for changes")
    alert_on_first_check: bool = Field(default=False, description="Alert on first check (baseline)")
    keyword_monitoring: bool = Field(default=True, description="Enable keyword monitoring")
    price_monitoring: bool = Field(default=True, description="Enable price monitoring")
    database_path: str = Field(default="~/.local/share/webscout/monitor.db", description="Monitor database path")


class SSRFConfig(BaseModel):
    """SSRF protection configuration."""

    enabled: bool = Field(default=True, description="Enable SSRF protection")
    block_localhost: bool = Field(default=True, description="Block localhost/127.0.0.1")
    block_private_ips: bool = Field(default=True, description="Block private IP ranges (10.x, 172.16-31.x, 192.168.x)")
    block_link_local: bool = Field(default=True, description="Block link-local addresses (169.254.x)")
    block_metadata: bool = Field(default=True, description="Block cloud metadata endpoints (169.254.169.254)")
    allowed_schemes: list[str] = Field(default_factory=lambda: ["http", "https"], description="Allowed URL schemes")
    blocked_ports: list[int] = Field(
        default_factory=lambda: [22, 25, 3306, 5432, 6379, 27017],
        description="Blocked ports (sensitive services)",
    )
    max_redirects: int = Field(default=5, ge=0, le=20, description="Max redirects to follow")
    dns_rebinding_protection: bool = Field(default=True, description="Enable DNS rebinding protection")


class RateLimitConfig(BaseModel):
    """Rate limiting configuration."""

    enabled: bool = Field(default=True, description="Enable rate limiting")
    requests_per_second: float = Field(default=1.0, gt=0, description="Max requests per second per domain")
    requests_per_minute: int = Field(default=60, ge=1, description="Max requests per minute per domain")
    requests_per_hour: int = Field(default=1000, ge=1, description="Max requests per hour per domain")
    burst_size: int = Field(default=5, ge=1, description="Allowed burst size")
    per_domain: bool = Field(default=True, description="Apply rate limit per domain")
    global_limit: int = Field(default=100, ge=1, description="Global max concurrent requests")


class WebScoutConfig(BaseModel):
    """Main configuration for webscout-mcp.

    Aggregates all configuration sections with validation and
    environment variable support.
    """

    server: ServerConfig = Field(default_factory=ServerConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    vector_store: VectorStoreConfig = Field(default_factory=VectorStoreConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    monitor: MonitorConfig = Field(default_factory=MonitorConfig)
    ssrf: SSRFConfig = Field(default_factory=SSRFConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)

    @model_validator(mode="after")
    def validate_dependencies(self):
        """Validate cross-section dependencies."""
        # If vector store is enabled but embedding backend is local, ensure dimension matches
        if self.vector_store.enabled and self.vector_store.embedding_backend == "local":
            if self.vector_store.embedding_model == "BAAI/bge-small-zh-v1.5":
                if self.vector_store.embedding_dimension != 384:
                    log.warning("Embedding dimension may not match model, expected 384")

        # If AI backend is ollama, ensure ollama_host is set
        if self.ai.backend == "ollama" and not self.ai.ollama_host:
            raise ValueError("ollama_host must be set when backend is 'ollama'")

        # If browser proxy is set, ensure it's valid format
        if self.browser.proxy and not self.browser.proxy.startswith(("http://", "https://", "socks5://")):
            raise ValueError("Proxy URL must start with http://, https://, or socks5://")

        return self

    @classmethod
    def from_env(cls) -> "WebScoutConfig":
        """Load configuration from environment variables.

        Environment variables format: WEBSCOUT_<SECTION>_<KEY>
        Example: WEBSCOUT_SEARCH_MAX_RESULTS=20
        """
        config = cls()
        prefix = "WEBSCOUT_"

        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue

            # Remove prefix and split
            parts = key[len(prefix) :].lower().split("_", 1)
            if len(parts) != 2:
                continue

            section_name, field_name = parts

            # Find section
            section = getattr(config, section_name, None)
            if section is None:
                continue

            # Set field if it exists
            if hasattr(section, field_name):
                try:
                    # Type conversion
                    current_value = getattr(section, field_name)
                    if isinstance(current_value, bool):
                        setattr(section, field_name, value.lower() in ("true", "1", "yes"))
                    elif isinstance(current_value, int):
                        setattr(section, field_name, int(value))
                    elif isinstance(current_value, float):
                        setattr(section, field_name, float(value))
                    elif isinstance(current_value, list):
                        setattr(section, field_name, [v.strip() for v in value.split(",")])
                    else:
                        setattr(section, field_name, value)
                except (ValueError, TypeError):
                    log.warning(f"Invalid env value for {key}: {value}")

        return config

    def to_dict(self) -> dict:
        """Serialize configuration to dictionary."""
        return self.model_dump()

    def to_json(self, indent: int = 2) -> str:
        """Serialize configuration to JSON string."""
        import json

        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "WebScoutConfig":
        """Load configuration from dictionary."""
        return cls.model_validate(data)

    def get_section(self, name: str) -> Optional[BaseModel]:
        """Get a configuration section by name."""
        return getattr(self, name, None)

    def list_sections(self) -> list[str]:
        """List all configuration section names."""
        return [f for f in type(self).model_fields.keys()]


def load_config(config_path: Optional[str] = None) -> WebScoutConfig:
    """Load configuration from file and/or environment.

    Priority: environment variables > config file > defaults

    Args:
        config_path: Path to config file (JSON/TOML/YAML).

    Returns:
        Loaded WebScoutConfig instance.
    """
    config = WebScoutConfig()

    # Load from file if provided
    if config_path and os.path.exists(config_path):
        try:
            if config_path.endswith(".json"):
                import json

                with open(config_path, "r") as f:
                    data = json.load(f)
                config = WebScoutConfig.from_dict(data)
            elif config_path.endswith(".toml"):
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib
                with open(config_path, "rb") as f:
                    data = tomllib.load(f)
                config = WebScoutConfig.from_dict(data)
            elif config_path.endswith((".yaml", ".yml")):
                import yaml

                with open(config_path, "r") as f:
                    data = yaml.safe_load(f)
                config = WebScoutConfig.from_dict(data)
            log.info(f"Loaded config from {config_path}")
        except Exception as exc:
            log.error(f"Failed to load config from {config_path}: {exc}")

    # Override with environment variables
    env_config = WebScoutConfig.from_env()
    # Merge: env values override file values
    for section_name in config.list_sections():
        file_section = getattr(config, section_name)
        env_section = getattr(env_config, section_name)
        for field_name in type(file_section).model_fields:
            env_value = getattr(env_section, field_name)
            default_value = getattr(type(file_section)(), field_name)
            # If env value differs from default, use it
            if env_value != default_value:
                setattr(file_section, field_name, env_value)

    return config
