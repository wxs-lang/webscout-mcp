"""Unified WebResult model for WebScout v1.3.0.

This is the internal contract every search/fetch path produces before it
reaches an MCP tool. It is deliberately a *superset* of what any single
backend returns: callers can rely on the common fields and ignore the
backend-specific metadata.

Privacy rules:
  * ``metadata`` never carries cookies, Authorization, tokens, or full
    credential-bearing URLs.
  * ``published_at`` is ``None`` unless the source gave a reliable date;
    we never guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class WebResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


# Backend values are stable strings used by observability and debugging.
BACKEND_FAST_HTTP = "fast-http"
BACKEND_CRAWL4AI = "crawl4ai"
BACKEND_SEARCH = "search"  # a search hit, not a fetched page


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WebResult:
    """Unified result for both search hits and fetched pages."""

    url: str
    title: str = ""
    content: str = ""
    source: str = ""  # real provider that produced this (e.g. bing / searxng / crawl4ai)
    backend: str = ""  # the layer that actually returned it
    content_type: str = ""
    retrieved_at: str = field(default_factory=_utcnow_iso)
    published_at: str | None = None
    status: WebResultStatus = WebResultStatus.SUCCESS
    metadata: dict[str, Any] = field(default_factory=dict)

    # --- Content-quality basics (P0-5). Deterministic, no LLM. ---
    @property
    def content_length(self) -> int:
        return len(self.content or "")

    @property
    def empty_content(self) -> bool:
        return self.content_length == 0

    @property
    def truncated(self) -> bool:
        return bool(self.metadata.get("truncated", False))

    @property
    def extraction_success(self) -> bool:
        return not bool(self.metadata.get("extraction_failed", False))

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "source": self.source,
            "backend": self.backend,
            "content_type": self.content_type,
            "retrieved_at": self.retrieved_at,
            "published_at": self.published_at,
            "status": self.status.value,
            "metadata": dict(self.metadata),
        }
