"""Content-quality gates in the SLO aggregator (GOAL G1/G5).

The aggregator is what turns a run's snapshot into a published SLO verdict, so
these tests pin the semantics that decide whether a release is declared healthy:
missing data must never be read as zero quality, and a usable-content shortfall
must surface as a violation rather than a warning.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from slo_aggregator import SLO_TARGETS, _extract_content_quality, aggregate_slo_metrics  # noqa: E402


def _report(content_quality=None, *, timestamp=None) -> dict:
    report = {
        "timestamp": time.time() if timestamp is None else timestamp,
        "search": {
            "count": 100,
            "success_count": 100,
            "p50_latency_ms": 400,
            "p95_latency_ms": 900,
        },
        "fetch": {
            "count": 100,
            "success_count": 100,
            "p50_latency_ms": 500,
            "p95_latency_ms": 2000,
        },
    }
    if content_quality is not None:
        report["content_quality"] = content_quality
    return report


def _cq(fetches=100, usable=95, thin=3, empty=2, truncated=10) -> dict:
    return {
        "fetches": fetches,
        "usable": usable,
        "thin": thin,
        "empty": empty,
        "truncated_by_output_limit": truncated,
    }


def test_extract_returns_none_for_reports_without_the_block():
    assert _extract_content_quality({}) is None
    assert _extract_content_quality({"content_quality": {}}) is None
    assert _extract_content_quality({"content_quality": "nonsense"}) is None


def test_extract_returns_none_for_zero_fetches():
    """A block with no fetches is not a measurement of zero quality."""
    assert _extract_content_quality({"content_quality": _cq(fetches=0, usable=0, thin=0, empty=0)}) is None


def test_extract_tolerates_junk_values():
    assert _extract_content_quality({"content_quality": {"fetches": "many"}}) is None


def test_healthy_when_everything_meets_target():
    result = aggregate_slo_metrics([_report(_cq())], 7)
    assert result["status"] == "healthy", result["violations"]
    assert result["content_quality"]["status"] == "measured"
    assert result["content_quality"]["usable_rate"] == 95.0


def test_low_usable_content_is_a_violation():
    result = aggregate_slo_metrics([_report(_cq(usable=60, thin=30, empty=10))], 7)
    assert result["status"] == "violating"
    assert any("Usable content rate" in v for v in result["violations"])


def test_thin_content_excess_is_reported():
    result = aggregate_slo_metrics([_report(_cq(usable=88, thin=12, empty=0))], 7)
    assert any("Thin content rate" in v for v in result["violations"])


def test_truncation_excess_is_not_a_gate_at_all():
    """Truncation is information, not a warning.

    This test previously asserted "warning", which encoded the belief that a
    high truncation rate indicates a problem. It does not. has_more=True means
    the body was fully fetched and extracted and the caller is receiving the
    first window, with start_char available to continue - so the rate tracks
    page length, not service quality.

    The first real baseline made this concrete: 70% truncation alongside 100%
    usable content scored "warning" for no reason. Any documentation-heavy
    corpus would alert permanently. It is now reported under "notes".
    """
    result = aggregate_slo_metrics([_report(_cq(usable=95, thin=2, empty=3, truncated=50))], 7)
    assert result["status"] == "healthy", result["violations"]
    assert not any("Truncation" in v for v in result["violations"])
    assert any("Truncation" in n for n in result["notes"])


def test_a_violation_is_not_downgraded_by_a_later_warning():
    """Ordering must not let a warning overwrite a hard violation."""
    result = aggregate_slo_metrics([_report(_cq(usable=10, thin=50, empty=40, truncated=90))], 7)
    assert result["status"] == "violating"


def test_legacy_reports_report_no_data_not_zero_quality():
    result = aggregate_slo_metrics([_report()], 7)
    cq = result["content_quality"]
    assert cq["status"] == "no_data"
    assert cq["usable_rate"] is None
    assert cq["reports_with_data"] == 0
    # A report that predates the instrumentation must not fail the gate.
    assert result["status"] == "healthy"


def test_mixed_reports_only_count_the_ones_with_data():
    reports = [_report(_cq(usable=90, thin=5, empty=5)), _report()]
    result = aggregate_slo_metrics(reports, 7)
    cq = result["content_quality"]
    assert cq["reports_with_data"] == 1
    assert cq["fetches"] == 100
    assert cq["usable_rate"] == 90.0


def test_rates_aggregate_across_reports_by_count_not_by_average():
    """Pooled counts, not a mean of per-report rates."""
    a = _report(_cq(fetches=100, usable=100, thin=0, empty=0, truncated=0))
    b = _report(_cq(fetches=900, usable=0, thin=900, empty=0, truncated=0))
    result = aggregate_slo_metrics([a, b], 7)
    assert result["content_quality"]["fetches"] == 1000
    assert result["content_quality"]["usable_rate"] == 10.0


def test_targets_are_configurable_and_have_documented_defaults():
    assert SLO_TARGETS["usable_content_rate_min"] == 85.0
    assert SLO_TARGETS["thin_content_rate_max"] == 10.0
    assert SLO_TARGETS["truncation_rate_max"] == 25.0


def test_no_data_period_still_returns_structured_result():
    result = aggregate_slo_metrics([], 7)
    assert result["status"] == "no_data"
    assert result["data_points"] == 0
