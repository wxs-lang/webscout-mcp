"""Truncation is a page-length fact, not a service failure.

The first real baseline reported:

    usable_rate      = 100.0%
    truncation_rate  =  70.0%
    status           = warning   <- because of the truncation gate

Both numbers were correct. has_more=True means the full body was fetched and
extracted and the caller is being served the first window, with start_char
available to read on (progressive delivery, Phase 2.7C). So the rate measures
how long the pages in the corpus are, not how well the service did.

Gating on it alerts whenever the corpus contains long pages - which for a
web-research tool is always. Measured directly: a 577-char page and a 711-char
page never truncate; a 34603-char page and a 25399-char page always do.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def agg():
    spec = importlib.util.spec_from_file_location("slo_aggregator_truncation_under_test", SCRIPTS / "slo_aggregator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(*, fetches: int = 10, usable: int = 10, truncated: int = 7, searches: int = 40) -> dict:
    return {
        "timestamp": time.time(),
        "search": {"count": searches, "success_count": searches, "p50_latency_ms": 218.0, "p95_latency_ms": 623.0},
        "fetch": {"count": fetches, "success_count": fetches, "p50_latency_ms": 500.0, "p95_latency_ms": 2000.0},
        "content_quality": {
            "fetches": fetches,
            "usable": usable,
            "thin": fetches - usable,
            "empty": 0,
            "truncated_by_output_limit": truncated,
        },
    }


# --- The exact situation the first baseline hit ------------------------


def test_high_truncation_with_full_usable_rate_is_healthy(agg):
    """70% truncated and 100% usable is a correct reading, not a defect."""
    result = agg.aggregate_slo_metrics([_report()], 7)
    assert result["content_quality"]["usable_rate"] == 100.0
    assert result["content_quality"]["truncation_rate"] == 70.0
    assert result["status"] == "healthy"


def test_truncation_never_appears_in_violations(agg):
    result = agg.aggregate_slo_metrics([_report()], 7)
    assert not any("Truncation" in v for v in result["violations"])


def test_truncation_is_reported_as_a_note(agg):
    """It must stay visible - just not as an alert."""
    result = agg.aggregate_slo_metrics([_report()], 7)
    assert any("Truncation" in n for n in result["notes"])
    assert any("progressive" in n for n in result["notes"])


def test_low_truncation_produces_no_note(agg):
    result = agg.aggregate_slo_metrics([_report(truncated=1)], 7)
    assert not any("Truncation" in n for n in result["notes"])


def test_truncation_does_not_downgrade_a_violation(agg):
    """A note must never mask a real problem."""
    result = agg.aggregate_slo_metrics([_report(usable=2, truncated=9)], 7)
    assert result["status"] == "violating"
    assert any("Usable content rate" in v for v in result["violations"])


# --- Gates that DO still apply ----------------------------------------


def test_thin_content_is_still_a_warning(agg):
    """Thin content remains a gate: a captcha shell is a real miss.

    Chosen so usable_rate stays above the 85% floor (100 usable, 12 thin, 112
    total) and only the thin rate breaches. Otherwise the hard violation would
    mask the warning being tested.
    """
    result = agg.aggregate_slo_metrics([_report(fetches=112, usable=100, truncated=0)], 7)
    assert result["content_quality"]["usable_rate"] == pytest.approx(89.29, abs=0.01)
    assert result["content_quality"]["thin_rate"] == pytest.approx(10.71, abs=0.01)
    assert result["status"] == "warning"
    assert any("Thin content rate" in v for v in result["violations"])
    assert not any("Usable content rate" in v for v in result["violations"])


def test_low_usable_rate_is_still_a_hard_violation(agg):
    result = agg.aggregate_slo_metrics([_report(usable=5, truncated=0)], 7)
    assert result["status"] == "violating"


# --- notes is always present in the payload ---------------------------


def test_result_always_carries_a_notes_key(agg):
    """Consumers should not have to special-case its absence."""
    result = agg.aggregate_slo_metrics([_report()], 7)
    assert "notes" in result
    assert isinstance(result["notes"], list)


def test_no_data_window_also_carries_notes(agg):
    empty = {
        "timestamp": time.time(),
        "search": {"count": 0, "success_count": 0},
        "fetch": {"count": 0, "success_count": 0},
        "content_quality": {"fetches": 0, "usable": 0, "thin": 0, "empty": 0, "truncated_by_output_limit": 0},
    }
    result = agg.aggregate_slo_metrics([empty], 7)
    assert result["status"] == "no_data"
    assert isinstance(result.get("notes"), list)
