"""Configuration management for webscout-mcp."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _default_cache_dir() -> Path:
    """Return the default cache directory."""
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "webscout"
    return Path.home() / ".cache" / "webscout"


@dataclass
class Config:
    """Runtime configuration for webscout-mcp.

    All values can be overridden via environment variables with the
    ``WEBSCOUT_`` prefix, e.g. ``WEBSCOUT_CACHE_TTL=3600``.
    """

    # --- Cache ---
    cache_dir: Path = field(default_factory=_default_cache_dir)
    cache_ttl: int = 7200  # seconds, default 2h
    cache_max_size_mb: int = 512

    # --- HTTP / fetching ---
    request_timeout: float = 15.0
    max_retries: int = 3
    retry_backoff: float = 0.5  # seconds, exponential
    user_agent: str = (
        "Mozilla/5.0 (compatible; webscout-mcp/0.1; "
        "+https://github.com/webscout-mcp/webscout-mcp)"
    )
    max_content_length: int = 5 * 1024 * 1024  # 5 MB

    # --- Rate limiting (per domain) ---
    rate_limit_per_second: float = 2.0
    rate_limit_burst: int = 5

    # --- Search ---
    search_max_results: int = 10
    search_safe_search: bool = True

    # --- Crawler ---
    crawler_max_depth: int = 2
    crawler_max_pages: int = 20
    crawler_same_domain_only: bool = True

    # --- Extraction ---
    extract_output_format: str = "markdown"  # markdown | text | html

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config instance, overriding defaults from environment."""
        kwargs: dict = {}
        env_map = {
            "WEBSCOUT_CACHE_DIR": ("cache_dir", lambda v: Path(v)),
            "WEBSCOUT_CACHE_TTL": ("cache_ttl", int),
            "WEBSCOUT_CACHE_MAX_SIZE_MB": ("cache_max_size_mb", int),
            "WEBSCOUT_REQUEST_TIMEOUT": ("request_timeout", float),
            "WEBSCOUT_MAX_RETRIES": ("max_retries", int),
            "WEBSCOUT_USER_AGENT": ("user_agent", str),
            "WEBSCOUT_RATE_LIMIT_PER_SECOND": ("rate_limit_per_second", float),
            "WEBSCOUT_SEARCH_MAX_RESULTS": ("search_max_results", int),
            "WEBSCOUT_CRAWLER_MAX_DEPTH": ("crawler_max_depth", int),
            "WEBSCOUT_CRAWLER_MAX_PAGES": ("crawler_max_pages", int),
            "WEBSCOUT_EXTRACT_OUTPUT_FORMAT": ("extract_output_format", str),
        }
        for env_key, (attr, converter) in env_map.items():
            raw = os.environ.get(env_key)
            if raw is not None:
                try:
                    kwargs[attr] = converter(raw)
                except (ValueError, TypeError):
                    pass  # keep default on invalid value
        return cls(**kwargs)

    def ensure_dirs(self) -> None:
        """Create cache directory if it doesn't exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
