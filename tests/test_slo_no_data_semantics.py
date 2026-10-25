"""A report that recorded nothing is not a passing report.

Three states used to be smeared into one, and the confusion inverted the meaning
of the metric:

    no reports            -> no_data          (correct)
    reports, no data      -> healthy          (wrong: a pipeline that never ran
                                               anything presented a green SLO)
    0% success rate       -> 0.0% + healthy?  (wrong before: it reported a
                                               violation even with no
                                               observations, because total=0
                                               produced rate 0.0)

Now: no observations means rate is None and the window is no_data; observations
that all failed means rate is 0.0 and the window is violating.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture(scope="module")
def agg():
    spec = importlib.util.spec_from_file_location("slo_aggregator_under_test", SCRIPTS / "slo_aggregator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _report(
    *,
    searches: int = 0,
    searches_ok: int = 0,
    fetches: int = 0,
    fetches_ok: int = 0,
    cq_fetches: int = 0,
    cq_usable: int = 0,
) -> dict:
    return {
        "timestamp": time.time(),
        "search": {"count": searches, "success_count": searches_ok},
        "fetch": {"count": fetches, "success_count": fetches_ok},
        "content_quality": {
            "fetches": cq_fetches,
            "usable": cq_usable,
            "thin": cq_fetches - cq_usable,
            "empty": 0,
            "truncated_by_output_limit": 0,
        },
    }


# --- Four distinct states ----------------------------------------------


def test_no_reports_is_no_data(agg):
    result = agg.aggregate_slo_metrics([], 7)
    assert result["status"] == "no_data"
    assert result["data_points"] == 0


def test_reports_with_no_observations_are_not_healthy(agg):
    """The trap: three reports present, every counter zero.

    Counting presence rather than content made this a green SLO for a pipeline
    that had recorded nothing at all.
    """
    result = agg.aggregate_slo_metrics([_report(), _report(), _report()], 7)
    assert result["status"] == "no_data"
    assert result["data_points"] == 3, "the reports are still counted"
    assert any("no observations" in v for v in result["violations"])


def test_all_failed_is_violating(agg):
    result = agg.aggregate_slo_metrics([_report(searches=10, fetches=10, cq_fetches=10)], 7)
    assert result["status"] == "violating"
    assert result["search"]["success_rate"] == 0.0


def test_healthy_needs_actual_success(agg):
    result = agg.aggregate_slo_metrics(
        [_report(searches=40, searches_ok=40, fetches=10, fetches_ok=10, cq_fetches=10, cq_usable=10)], 7
    )
    assert result["status"] == "healthy"
    assert result["search"]["success_rate"] == 100.0


# --- None vs 0.0 is load-bearing ---------------------------------------


def test_no_observations_yield_none_not_zero(agg):
    result = agg.aggregate_slo_metrics([_report()], 7)
    assert result["search"]["success_rate"] is None
    assert result["fetch"]["success_rate"] is None


def test_zero_success_yields_zero_not_none(agg):
    result = agg.aggregate_slo_metrics([_report(searches=5, fetches=5)], 7)
    assert result["search"]["success_rate"] == 0.0
    assert result["fetch"]["success_rate"] == 0.0


def test_none_rates_do_not_trigger_success_violations(agg):
    """A no-data window must not accuse the service of failing every request."""
    result = agg.aggregate_slo_metrics([_report()], 7)
    assert not any("Search success rate" in v for v in result["violations"])
    assert not any("Fetch success rate" in v for v in result["violations"])


def test_latency_gate_skipped_when_there_are_no_samples(agg):
    """P95 of nothing is 0, which would look like a fast, healthy service."""
    result = agg.aggregate_slo_metrics([_report()], 7)
    assert not any("P95 latency" in v for v in result["violations"])


# --- Partial data ------------------------------------------------------


def test_one_empty_report_does_not_poison_a_good_window(agg):
    result = agg.aggregate_slo_metrics(
        [_report(searches=40, searches_ok=40, fetches=10, fetches_ok=10, cq_fetches=10, cq_usable=10), _report()], 7
    )
    assert result["status"] == "healthy"
    assert result["search"]["success_rate"] == 100.0, "the empty report adds no observations to the denominator"


def test_thirty_day_window_uses_its_own_targets(agg):
    result = agg.aggregate_slo_metrics([_report(searches=100, searches_ok=98, fetches=100, fetches_ok=97)], 30)
    assert result["status"] == "healthy", "98%/97% meet the 30d targets"
