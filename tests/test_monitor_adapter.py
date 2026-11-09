"""The monitor adapter: bridging an async pipeline into a synchronous fetcher.

`WebMonitor` calls `fetcher.fetch(url)` and reads `.content` / `.html`. `fetch_service`
is async and its response carries `.raw_html`, not `.html`. Both differences are bridged
here so monitoring inherits TLS impersonation, browser escalation and recovery
classification instead of a bare HTTP request that fails on exactly the pages monitoring
is most useful for.
"""

from __future__ import annotations

import asyncio

import pytest

from webscout_mcp.monitor_adapter import FetchServiceAdapter, MonitorFetchResult


class _Response:
    def __init__(self, content: str, raw_html: str = "", status: int = 200) -> None:
        self.content = content
        self.raw_html = raw_html
        self.status_code = status


class _Route:
    def __init__(self, response, outcome: str = "accepted") -> None:
        self.primary_response = response
        self.recovery_outcome = outcome


class _Service:
    """Stands in for fetch_service; records the request it was given."""

    def __init__(self, route=None, raise_with=None) -> None:
        self._route = route
        self._raise = raise_with
        self.requests: list = []

    async def fetch(self, request):
        self.requests.append(request)
        if self._raise is not None:
            raise self._raise
        return self._route


def _fetch_in_thread(adapter: FetchServiceAdapter, url: str):
    """The monitor always calls this from a worker thread; mirror that."""

    async def go():
        return await asyncio.to_thread(adapter.fetch, url)

    return asyncio.run(go())


# --- the happy path ---------------------------------------------------


def test_returns_content_and_html_from_the_route():
    service = _Service(_Route(_Response("page text", "<html>page text</html>")))
    adapter = FetchServiceAdapter(service)
    result = _fetch_in_thread(adapter, "https://example.test/")

    assert isinstance(result, MonitorFetchResult)
    assert result.content == "page text"
    assert result.html == "<html>page text</html>"
    assert result.status_code == 200


def test_html_falls_back_to_content_when_raw_html_is_absent():
    """`_get_content` treats an empty html as 'nothing fetched' and skips the check."""
    service = _Service(_Route(_Response("only text", raw_html="")))
    result = _fetch_in_thread(FetchServiceAdapter(service), "https://example.test/")
    assert result.html == "only text", "empty html must not silently skip the check"


def test_requests_raw_html_not_extracted_text():
    """Monitoring needs markup for change detection, and the pipeline needs to know."""
    service = _Service(_Route(_Response("x", "<html>x</html>")))
    _fetch_in_thread(FetchServiceAdapter(service), "https://example.test/")
    request = service.requests[0]
    assert request.extract is False
    assert request.output_format == "html"


def test_recovery_outcome_is_preserved():
    service = _Service(_Route(_Response("x"), outcome="browser_success"))
    adapter = FetchServiceAdapter(service)
    result = _fetch_in_thread(adapter, "https://example.test/")
    assert result.recovery_outcome == "browser_success"
    assert adapter.last_recovery_outcome == "browser_success"


# --- failure paths ----------------------------------------------------


def test_a_raising_service_returns_empty_instead_of_propagating():
    """Raising would abort the whole monitoring run; the monitor skips on empty."""
    service = _Service(raise_with=RuntimeError("boom"))
    result = _fetch_in_thread(FetchServiceAdapter(service), "https://example.test/")
    assert result.content == ""
    assert result.html == ""


def test_a_failure_records_why():
    """Empty content must not be confused with an empty page."""
    service = _Service(raise_with=RuntimeError("boom"))
    adapter = FetchServiceAdapter(service)
    _fetch_in_thread(adapter, "https://example.test/")
    assert "boom" in adapter.last_error


def test_calling_from_inside_a_running_loop_records_the_reason():
    """Silently returning empty here would look like a successful empty fetch.

    The monitor dispatches to a worker thread, so this path should not happen in normal
    use - but if a caller invokes the adapter directly from a coroutine, the reason must
    be visible rather than the baseline being overwritten with nothing.
    """
    service = _Service(_Route(_Response("page text")))
    adapter = FetchServiceAdapter(service)

    async def call_inside_loop():
        return adapter.fetch("https://example.test/")

    result = asyncio.run(call_inside_loop())
    assert result.content == ""
    assert "running event loop" in adapter.last_error


def test_success_clears_a_previous_error():
    service = _Service(_Route(_Response("ok", "<html>ok</html>")))
    adapter = FetchServiceAdapter(service)
    adapter.last_error = "stale failure"
    _fetch_in_thread(adapter, "https://example.test/")
    assert adapter.last_error == ""


def test_missing_primary_response_is_tolerated():
    class _EmptyRoute:
        primary_response = None
        recovery_outcome = ""

    service = _Service(_EmptyRoute())
    result = _fetch_in_thread(FetchServiceAdapter(service), "https://example.test/")
    assert result.content == ""
    assert result.html == ""


# --- wiring -----------------------------------------------------------


def test_web_monitor_uses_the_adapter():
    """Pins the fix: the tool must not let the monitor do its own HTTP."""
    import inspect

    from webscout_mcp.server import create_server

    src = inspect.getsource(create_server)
    idx = src.find("async def web_monitor")
    assert idx != -1
    body = src[idx:]
    assert "FetchServiceAdapter" in body, "web_monitor must route through fetch_service"
    assert (
        "WebMonitor(config=config, fetcher=FetchServiceAdapter(" in body.replace("\n", " ").replace("  ", " ")
        or "fetcher=FetchServiceAdapter(fetch_service)" in body
    ), "the monitor must be constructed with the adapter, not bare"
