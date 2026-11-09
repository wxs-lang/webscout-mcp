"""A 4xx must never be reported as retryable.

Two mechanisms combined to make it happen:

    _map_http_status_to_standard_code   every unlisted 4xx -> FETCH_SERVER_ERROR
    StructuredError.__post_init__       retryable=True whenever code is in
                                        RETRYABLE_ERROR_CODES

400, 402, 405, 409, 418 and 451 all landed in that path, so a caller was told a
malformed request was worth retrying - it is not, it fails identically every time.

The fix classifies by status class. These tests pin both the mapping table and the
resulting retryable flag, because the mapping alone is not what the caller sees.
"""

from __future__ import annotations

import pytest

from webscout_mcp.core.errors import (
    RETRYABLE_ERROR_CODES,
    StandardErrorCode,
    StructuredError,
    _map_http_status_to_standard_code,
)

# 4xx codes that have no dedicated branch - the ones the catch-all used to swallow
UNLISTED_4XX = [
    400,
    402,
    405,
    406,
    409,
    410,
    411,
    412,
    413,
    414,
    415,
    416,
    417,
    418,
    421,
    422,
    423,
    424,
    425,
    426,
    428,
    431,
    451,
]


@pytest.mark.parametrize("status", UNLISTED_4XX)
def test_unlisted_4xx_is_not_a_server_error(status):
    code = _map_http_status_to_standard_code(status)
    assert code is not StandardErrorCode.FETCH_SERVER_ERROR, (
        f"{status} is a client error but mapped to FETCH_SERVER_ERROR"
    )


@pytest.mark.parametrize("status", UNLISTED_4XX)
def test_unlisted_4xx_is_not_retryable(status):
    """The consequence that matters: retryable drives the actual retry loop."""
    code = _map_http_status_to_standard_code(status)
    assert code not in RETRYABLE_ERROR_CODES, f"{status} -> {code.name} is in the retryable set"


@pytest.mark.parametrize("status", UNLISTED_4XX)
def test_structured_error_from_4xx_reports_not_retryable(status):
    """End to end: __post_init__ promotes retryable by code, so a wrong code
    silently overrides what the caller would reasonably expect."""
    err = StructuredError(code=_map_http_status_to_standard_code(status), message="x")
    assert err.retryable is False, f"{status} produced retryable=True"


@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_5xx_stays_a_retryable_server_error(status):
    code = _map_http_status_to_standard_code(status)
    assert code is StandardErrorCode.FETCH_SERVER_ERROR
    assert StructuredError(code=code, message="x").retryable is True


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (400, StandardErrorCode.FETCH_FAILED),
        (403, StandardErrorCode.FETCH_FORBIDDEN),
        (404, StandardErrorCode.FETCH_NOT_FOUND),
        (408, StandardErrorCode.FETCH_TIMEOUT),
        (429, StandardErrorCode.FETCH_RATE_LIMITED),
        (418, StandardErrorCode.FETCH_FAILED),
        (301, StandardErrorCode.FETCH_REDIRECT_ERROR),
        (500, StandardErrorCode.FETCH_SERVER_ERROR),
    ],
)
def test_specific_codes_are_preserved(status, expected):
    """The catch-all fix must not disturb the branches that were already right."""
    assert _map_http_status_to_standard_code(status) is expected


def test_zero_is_not_a_server_error():
    """status_code=0 means no HTTP response at all; calling it a server error
    invents a status the server never sent."""
    code = _map_http_status_to_standard_code(0)
    assert code is StandardErrorCode.SYSTEM_ERROR
    assert code is not StandardErrorCode.FETCH_SERVER_ERROR


@pytest.mark.parametrize("status", [600, 999, 100, 101])
def test_non_error_statuses_fall_to_system_error(status):
    for code_value in (_map_http_status_to_standard_code(status),):
        assert code_value is StandardErrorCode.SYSTEM_ERROR


def test_retryable_flag_is_derived_from_the_code_set():
    """Documents the mechanism this fix works around.

    __post_init__ promotes retryable whenever the code is in the set, even if the
    caller passed False. That is why fixing the mapping - not passing
    retryable=False - is what actually stops 4xx retries.
    """
    retryable_code = next(iter(RETRYABLE_ERROR_CODES))
    assert StructuredError(code=retryable_code, message="x", retryable=False).retryable is True

    non_retryable = StandardErrorCode.FETCH_NOT_FOUND
    assert non_retryable not in RETRYABLE_ERROR_CODES
    assert StructuredError(code=non_retryable, message="x").retryable is False
