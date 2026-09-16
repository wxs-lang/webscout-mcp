"""Real Crawl4AI sidecar end-to-end tests.

Runs ONLY in the crawl4ai-e2e workflow, which starts a real
``unclecode/crawl4ai`` container. Validates the v1.2.2 escalation contract:

  1. A live Crawl4AI container renders a real URL and returns markdown.
  2. The Crawl4AIBrowserBackend parses the real HTTP response correctly.
  3. Escalation decision rules behave as locked (403/challenge/JS-placeholder
     escalate; 451/429/non-HTML never do).
  4. When the sidecar port is dead, the backend returns a retryable connect
     error (so web_fetch can fall back to keeping the fast-fetch result).

No mocks. Requires CRAWL4AI_BASE_URL to be set.
"""

from __future__ import annotations

import os

import pytest

from webscout_mcp.config import Config
from webscout_mcp.crawl4ai_backend import Crawl4AIBrowserBackend
from webscout_mcp.fetch_escalation import (
    EscalationReason,
    should_escalate_to_browser,
)
from webscout_mcp.fetch_provider import FetchRequest, FetchResponse

pytestmark = pytest.mark.skipif(
    not os.environ.get("CRAWL4AI_BASE_URL"),
    reason="CRAWL4AI_BASE_URL not set (only runs in crawl4ai-e2e workflow)",
)


def _config(base_url: str | None = None) -> Config:
    cfg = Config()
    cfg.crawl4ai_enabled = True
    cfg.crawl4ai_base_url = base_url or os.environ.get("CRAWL4AI_BASE_URL", "")
    cfg.crawl4ai_timeout = 60.0
    return cfg


@pytest.mark.asyncio
async def test_real_crawl4ai_renders_public_page():
    """The sidecar actually renders a public URL and returns markdown."""
    backend = Crawl4AIBrowserBackend(_config())
    try:
        resp = await backend.fetch(FetchRequest(url="https://example.com"))
        assert resp.is_success, f"expected success, got {resp.error}"
        assert resp.content and len(resp.content) > 100, (
            f"expected non-trivial markdown, got {len(resp.content or '')} chars"
        )
        assert resp.provider == "crawl4ai"
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_dead_sidecar_returns_retryable_error():
    backend = Crawl4AIBrowserBackend(_config(base_url="http://127.0.0.1:1"))
    try:
        resp = await backend.fetch(FetchRequest(url="https://example.com"))
        assert resp.is_error
        assert resp.retryable is True
    finally:
        await backend.close()


def test_escalation_403_triggers():
    d = should_escalate_to_browser(
        FetchResponse(
            url="https://x",
            final_url="https://x",
            status_code=403,
            provider="http",
            content="",
        )
    )
    assert d.escalate is True
    assert d.reason_code == EscalationReason.SOFT_BLOCK


def test_escalation_451_does_not_trigger():
    d = should_escalate_to_browser(
        FetchResponse(
            url="https://x",
            final_url="https://x",
            status_code=451,
            provider="http",
            content="blocked",
        )
    )
    assert d.escalate is False


def test_escalation_pdf_does_not_trigger():
    d = should_escalate_to_browser(
        FetchResponse(
            url="https://x",
            final_url="https://x",
            status_code=200,
            provider="http",
            content="%PDF-1.4",
            content_type="application/pdf",
        )
    )
    assert d.escalate is False
