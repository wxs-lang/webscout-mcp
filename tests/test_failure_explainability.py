"""C group: a failure must explain itself to the caller.

Measured at the MCP boundary before the fix:

    404 -> {"status_code": 404, "error": null}
    500 -> {"status_code": 500, "error": null}
    DNS -> {"status_code": 0,   "error": "Failed after 3 retries: "}

and the codes underneath were wrong, not merely hidden:

    404 -> FETCH_FAILED          while FETCH_NOT_FOUND existed and never appeared
    DNS -> FETCH_FAILED          because the message was stripped to
                                 "Failed after 3 retries: " and the mapper
                                 matched on text

GOAL.md C1 asks for codes rather than raw stacks; C2 asks every failure to carry
error_type and retryable. Neither held. These tests hold the four links now.
"""

from __future__ import annotations

import httpx
import pytest

from webscout_mcp.core.errors import StandardErrorCode
from webscout_mcp.fetch_provider import _map_fetch_error
from webscout_mcp.fetcher import _describe_exception

# --- Link 1: status codes map to specific, actionable codes -------------


def test_404_maps_to_not_found():
    """It used to fall through to FETCH_FAILED, making recovery.py's
    FETCH_NOT_FOUND branch unreachable."""
    code, retryable = _map_fetch_error(404, "HTTP 404 Not Found")
    assert code is StandardErrorCode.FETCH_NOT_FOUND
    assert retryable is False


def test_403_maps_to_forbidden_and_is_not_retryable():
    code, retryable = _map_fetch_error(403, "HTTP 403 Forbidden")
    assert code is StandardErrorCode.FETCH_FORBIDDEN
    assert retryable is False


def test_429_maps_to_rate_limited_and_is_retryable():
    code, retryable = _map_fetch_error(429, "HTTP 429 Too Many Requests")
    assert code is StandardErrorCode.FETCH_RATE_LIMITED
    assert retryable is True


def test_500_maps_to_server_error_and_is_retryable():
    code, retryable = _map_fetch_error(500, "HTTP 500 Internal Server Error")
    assert code is StandardErrorCode.FETCH_SERVER_ERROR
    assert retryable is True


def test_timeout_is_retryable():
    code, retryable = _map_fetch_error(408, "timed out")
    assert code is StandardErrorCode.FETCH_TIMEOUT
    assert retryable is True


def test_success_has_no_error_code():
    assert _map_fetch_error(200, None) == (None, False)


def test_404_is_not_the_generic_failure_code():
    """The specific case this fixed: a bare 404 must not be indistinguishable
    from every other 4xx."""
    code, _ = _map_fetch_error(404, None)
    assert code is not StandardErrorCode.FETCH_FAILED


# --- Link 2: the retry message must never be empty ----------------------


def test_empty_exception_renders_as_its_type_name():
    """str(httpx.ConnectError(...)) can be "", which produced
    "Failed after 3 retries: " - a sentence with nothing after the colon."""

    class Silent(Exception):
        def __str__(self) -> str:
            return ""

    assert _describe_exception(Silent()) == "Silent"


def test_exception_with_message_keeps_both():
    out = _describe_exception(ValueError("bad url"))
    assert out == "ValueError: bad url"


def test_none_is_described_not_blank():
    out = _describe_exception(None)
    assert out.strip(), "must not render as an empty string"
    assert "no error" in out.lower()


def test_connect_error_describes_itself():
    """A DNS failure surfaces as httpx.ConnectError; naming it lets the mapper
    reach a connection-level code instead of the generic bucket."""
    out = _describe_exception(httpx.ConnectError("Name or service not known"))
    assert "ConnectError" in out
    assert "Name or service not known" in out


def test_a_blank_message_still_maps_to_a_specific_code():
    """End to end: the old chain produced empty text, so the mapper returned
    FETCH_FAILED. With the type name present it reaches a connection code."""
    described = _describe_exception(httpx.ConnectError(""))
    code, retryable = _map_fetch_error(0, f"Failed after 3 retries: {described}")
    assert code is StandardErrorCode.FETCH_CONNECTION_ERROR
    assert retryable is True


# --- Link 3: the payload carries the code and the retry verdict ---------


def _route(primary):
    """Wrap a FetchResponse in the route object legacy_out lives on.

    FetchRouteResult requires primary_response, final_response and web_result;
    WebResult only needs a url.
    """
    from webscout_mcp.fetch_service import FetchRouteResult, WebResult

    return FetchRouteResult(
        primary_response=primary,
        final_response=primary,
        web_result=WebResult(url=primary.url),
    )


def test_legacy_out_exposes_error_code_and_retryable():
    from webscout_mcp.fetch_provider import FetchResponse

    primary = FetchResponse(
        url="https://example.test/missing",
        final_url="https://example.test/missing",
        status_code=404,
        provider="http",
        content="",
        error="HTTP 404 Not Found",
        error_code=StandardErrorCode.FETCH_NOT_FOUND,
        retryable=False,
    )
    out = _route(primary).legacy_out(max_chars=4000)
    assert out["error_code"] == "FETCH_NOT_FOUND"
    assert out["retryable"] is False
    assert out["error"] == "HTTP 404 Not Found"


def test_legacy_out_keeps_error_code_null_on_success():
    from webscout_mcp.fetch_provider import FetchResponse

    primary = FetchResponse(
        url="https://example.test/ok",
        final_url="https://example.test/ok",
        status_code=200,
        provider="http",
        content="hello",
    )
    out = _route(primary).legacy_out(max_chars=4000)
    assert out["error_code"] is None
    assert out["retryable"] is False


def test_legacy_out_shape_is_additive_only():
    """COMPATIBILITY.md freezes names and schema; adding keys is allowed."""
    from webscout_mcp.fetch_provider import FetchResponse

    primary = FetchResponse(
        url="https://example.test/ok",
        final_url="https://example.test/ok",
        status_code=200,
        provider="http",
        content="hello",
    )
    out = _route(primary).legacy_out(max_chars=4000)
    # The pre-existing keys must all still be present.
    for key in (
        "url",
        "final_url",
        "status_code",
        "title",
        "content",
        "content_type",
        "extracted",
        "cached",
        "error",
        "latency_ms",
    ):
        assert key in out, f"{key} disappeared from the payload"
    assert "error_code" in out and "retryable" in out


# --- Link 4: recovery sees the corrected code --------------------------


def test_recovery_not_found_branch_is_no_longer_dead():
    """recovery.py branches on FETCH_NOT_FOUND; before the mapping fix that
    branch could never be reached from a real 404."""
    from webscout_mcp.fetch_provider import FetchResponse
    from webscout_mcp.recovery import classify_recovery

    class _Resp:
        pass

    resp = FetchResponse(
        url="https://example.test/missing",
        final_url="https://example.test/missing",
        status_code=404,
        provider="http",
        content="",
        error="HTTP 404 Not Found",
        error_code=StandardErrorCode.FETCH_NOT_FOUND,
    )
    decision = classify_recovery(resp)
    assert decision.reason.value == "ACCESS_DENIED"
    assert decision.action.value == "STOP"
