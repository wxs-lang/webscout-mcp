"""Deterministic tests for content-usability telemetry (GOAL G1/G4).

These tests do not touch the network. They pin the semantics that make
"did we actually get usable content?" observable, which is the gap that let
the v1.9.0 A/B run report a 7.3pp content-usability deficit while every
success-rate metric stayed green.
"""

from __future__ import annotations

import pytest

from webscout_mcp import observability
from webscout_mcp.observability import (
    THIN_CONTENT_CHARS,
    get_observability_summary,
    record_content_quality,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_for_tests()
    yield
    reset_for_tests()


def _cq() -> dict:
    return get_observability_summary()["content_quality"]


def test_thin_threshold_is_low_enough_to_catch_captcha_shells() -> None:
    """A 200 with a captcha/nav shell must land in the thin bucket."""
    assert 0 < THIN_CONTENT_CHARS <= 500


def test_usable_content_is_counted() -> None:
    record_content_quality(returned_chars=5000, backend="fast-http", status="success")
    cq = _cq()
    assert cq["fetches"] == 1
    assert cq["usable"] == 1
    assert cq["thin"] == 0
    assert cq["empty"] == 0
    assert cq["usable_rate"] == 1.0


def test_thin_content_is_counted_separately_from_usable() -> None:
    record_content_quality(returned_chars=50, backend="fast-http", status="success")
    cq = _cq()
    assert cq["thin"] == 1
    assert cq["usable"] == 0
    assert cq["thin_rate"] == 1.0


def test_empty_content_is_counted() -> None:
    record_content_quality(returned_chars=0, backend="fast-http", status="success")
    cq = _cq()
    assert cq["empty"] == 1
    assert cq["empty_rate"] == 1.0
    assert cq["thin"] == 0


def test_boundary_at_threshold_is_usable() -> None:
    """Exactly THIN_CONTENT_CHARS chars must count as usable, not thin."""
    record_content_quality(returned_chars=THIN_CONTENT_CHARS)
    cq = _cq()
    assert cq["usable"] == 1
    assert cq["thin"] == 0


def test_one_below_threshold_is_thin() -> None:
    record_content_quality(returned_chars=THIN_CONTENT_CHARS - 1)
    cq = _cq()
    assert cq["thin"] == 1
    assert cq["usable"] == 0


def test_truncation_is_its_own_signal() -> None:
    """Truncated-but-thin and truncated-but-usable are different defects."""
    record_content_quality(
        returned_chars=8000,
        pre_limit_chars=200000,
        truncated=True,
        omitted_chars=192000,
        backend="fast-http",
        status="partial",
    )
    cq = _cq()
    assert cq["truncated_by_output_limit"] == 1
    assert cq["truncation_rate"] == 1.0
    assert cq["usable"] == 1, "a full window of a long page is still usable"
    assert cq["chars_omitted_total"] == 192000


def test_rates_are_zero_not_division_error_when_empty() -> None:
    cq = _cq()
    assert cq["fetches"] == 0
    assert cq["usable_rate"] == 0.0
    assert cq["thin_rate"] == 0.0
    assert cq["empty_rate"] == 0.0
    assert cq["truncation_rate"] == 0.0


def test_rates_are_fractions_within_unit_interval() -> None:
    for chars in (0, 50, 5000):
        record_content_quality(returned_chars=chars)
    cq = _cq()
    assert cq["fetches"] == 3
    for key in ("usable_rate", "thin_rate", "empty_rate", "truncation_rate"):
        assert 0.0 <= cq[key] <= 1.0, key
    # 0 -> empty, 50 -> thin, 5000 -> usable: each exactly one of three.
    assert cq["empty"] == 1 and cq["thin"] == 1 and cq["usable"] == 1


def test_per_backend_and_per_status_breakdown() -> None:
    record_content_quality(returned_chars=5000, backend="fast-http", status="success")
    record_content_quality(returned_chars=5000, backend="crawl4ai", status="success")
    record_content_quality(returned_chars=0, backend="crawl4ai", status="failed")
    cq = _cq()
    assert cq["by_backend"] == {"fast-http": 1, "crawl4ai": 2}
    assert cq["by_status"] == {"success": 2, "failed": 1}


def test_percentiles_track_returned_sizes() -> None:
    for n in (100, 200, 3000, 10000):
        record_content_quality(returned_chars=n)
    cq = _cq()
    assert cq["samples"] == 4
    assert cq["returned_p50"] >= 200
    assert cq["returned_p95"] >= cq["returned_p50"]


def test_ring_buffer_is_bounded() -> None:
    for _ in range(observability._MAX_CONTENT_SAMPLES + 50):
        record_content_quality(returned_chars=1000)
    cq = _cq()
    assert cq["samples"] == observability._MAX_CONTENT_SAMPLES


def test_negative_chars_are_clamped() -> None:
    record_content_quality(returned_chars=-5)
    cq = _cq()
    assert cq["empty"] == 1
    assert cq["chars_returned_total"] == 0


def test_no_content_ever_reaches_the_counters() -> None:
    """The recorder only accepts scalars; the summary must not echo content."""
    marker = "SECRETBODY-MARKER"
    record_content_quality(returned_chars=len(marker), backend="fast-http", status="success")
    blob = str(get_observability_summary())
    assert marker not in blob


def test_recorder_accepts_scalars_only_by_signature() -> None:
    """The recorder's signature cannot carry page content at all.

    The package logger sets ``propagate = False`` and defaults to WARNING, so
    asserting on captured log records is brittle here. Instead we assert the
    stronger structural property: there is no parameter through which content
    could be passed, so no future caller can leak a body through this path.
    """
    import inspect

    params = set(inspect.signature(record_content_quality).parameters)
    assert params == {
        "returned_chars",
        "pre_limit_chars",
        "truncated",
        "omitted_chars",
        "backend",
        "status",
    }
    for forbidden in ("content", "body", "html", "text", "url", "headers"):
        assert forbidden not in params


def test_reset_clears_content_quality() -> None:
    record_content_quality(returned_chars=5000)
    assert _cq()["fetches"] == 1
    reset_for_tests()
    cq = _cq()
    assert cq["fetches"] == 0
    assert cq["samples"] == 0
    assert cq["chars_returned_total"] == 0
