"""A 200 whose recovery failed must say so; a 4xx must keep saying what it already says.

## The defect, measured on medium.com

    classifier:   LOW_CONTENT_DENSITY -> BROWSER   (134 chars extracted from 52 KB)
    browser:      attempted, failed
    returned:     primary, 134 chars, error=None, error_code=None, extracted=True
    outcome:      browser_failed

The pipeline knew the extraction had collapsed and knew recovery had failed, then handed
back a payload claiming `error=None` with `extracted=True`. Only `outcome` carried the truth,
and `outcome` is a routing label - not something a caller can show a user.

## Why the fix is scoped to 2xx

`tests/test_403_recovery.py` pins `final_response.error is None` for a 403: the status code
and the structured error code *are* the explanation, and a synthetic message on top would
bury the original. The bug is narrower - a 200 where nothing in the payload said anything
was wrong.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from webscout_mcp.fetch_provider import FetchRequest, FetchResponse
from webscout_mcp.fetch_service import FetchService
from webscout_mcp.provider_registry import ProviderRegistry
from webscout_mcp.provider_router import ProviderCapability, ProviderCostTier, ProviderRouter

MEDIUM_NAV = "Our story\nMembership\nWrite\nSign in\nAbout Help Terms Privacy"
# 52 KB of markup, mirroring the measured medium page.
BIG_SHELL = "<html><body>" + ("<div class='x'>y</div>" * 2200) + "</body></html>"


def _resp(
    *,
    status_code: int = 200,
    content: str = "",
    provider: str = "http",
    error: str | None = None,
    raw_html: str = "",
    extracted: bool = True,
) -> FetchResponse:
    return FetchResponse(
        url="https://example.com/page",
        final_url="https://example.com/page",
        status_code=status_code,
        provider=provider,
        content=content,
        content_type="text/html",
        error=error,
        raw_html=raw_html,
        extracted=extracted,
    )


class _FakeProvider:
    def __init__(self, name: str, caps: set, response: FetchResponse):
        self.name = name
        self.capabilities = caps
        self.fetch = AsyncMock(return_value=response)
        self.close = AsyncMock()

    def get_health(self):
        return {"status": "ok"}


def _service(providers: list[_FakeProvider]) -> FetchService:
    router = ProviderRouter(
        provider_names=[p.name for p in providers],
        cost_tiers={p.name: ProviderCostTier.FREE for p in providers},
        capabilities={p.name: set(p.capabilities) for p in providers},
    )
    reg = ProviderRegistry(router=router)
    for p in providers:
        reg.register(p, capabilities=p.capabilities)
    return FetchService(registry=reg)


def _run(svc: FetchService):
    return asyncio.run(svc.fetch(FetchRequest(url="https://example.com/page")))


def test_a_200_with_failed_recovery_is_explained():
    """The medium case: 200, thin body from a large page, recovery failed, silence."""
    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=200, content=MEDIUM_NAV, raw_html=BIG_SHELL),
    )
    browser = _FakeProvider(
        "browser",
        {ProviderCapability.BROWSER},
        _resp(status_code=500, content="", provider="browser", error="browser unavailable"),
    )
    route = _run(_service([http, browser]))

    assert route.browser_attempted
    assert not route.browser_success
    assert route.final_response.error is not None, (
        "a 200 whose recovery failed must explain itself; silence is the defect"
    )
    assert "not complete" in route.final_response.error


def test_a_403_keeps_its_own_explanation():
    """The status code is the explanation; do not bury it with a synthetic message."""
    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=403, content="forbidden", raw_html="<html><body>forbidden</body></html>"),
    )
    browser = _FakeProvider(
        "browser",
        {ProviderCapability.BROWSER},
        _resp(status_code=500, content="", provider="browser", error="browser unavailable"),
    )
    route = _run(_service([http, browser]))

    assert route.final_response.status_code == 403
    assert route.final_response.error is None, (
        "a 4xx explains itself through its status; a synthetic message would bury it"
    )


def test_an_accepted_200_is_not_given_a_synthetic_error():
    """Normal fetches must stay silent - the check targets failures only."""
    body = "A real article with plenty of prose. " * 200
    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=200, content=body, raw_html="<html><body>" + ("<p>text</p>" * 200) + "</body></html>"),
    )
    route = _run(_service([http]))

    assert route.final_response.error is None, "a successful fetch must not carry an error"


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_keep_their_status(status):
    """Same rule for 5xx: the code explains, and it must survive."""
    http = _FakeProvider(
        "http",
        {ProviderCapability.FETCH},
        _resp(status_code=status, content="error", raw_html="<html><body>error</body></html>"),
    )
    route = _run(_service([http]))
    assert route.final_response.status_code == status
