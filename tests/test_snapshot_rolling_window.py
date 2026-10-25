"""Snapshots must be dateable, or the rolling SLO window cannot roll.

Two defects made the "7d / 30d" windows fiction:

1. ``write_snapshot`` emitted no ``timestamp``. The aggregator treats a report
   without one as legacy and includes it in *every* window, so nothing was ever
   filtered out - the windows covered all history forever.
2. CI never carried history between runs: each job starts from a fresh
   checkout and artifacts are per-run. Even with a timestamp, the window would
   have had exactly one sample to average.

These tests pin the timestamp and the resulting window arithmetic. The CI side
is covered by the workflow itself (an orphan ``slo-history`` branch); what is
testable here is that a report carrying a timestamp lands in the right window.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from webscout_mcp.observability import (
    get_observability_summary,
    read_snapshot,
    record_content_quality,
    reset_for_tests,
    write_snapshot,
)

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _aggregator():
    import importlib.util

    spec = importlib.util.spec_from_file_location("slo_aggregator_under_test", SCRIPTS / "slo_aggregator.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _clean():
    reset_for_tests()
    yield
    reset_for_tests()


# --- The snapshot must be dateable -------------------------------------


def test_summary_carries_a_timestamp():
    record_content_quality(returned_chars=5000, status="success")
    summary = get_observability_summary()
    assert "timestamp" in summary, "without this the aggregator cannot window the report"
    assert isinstance(summary["timestamp"], (int, float))


def test_timestamp_is_close_to_now():
    record_content_quality(returned_chars=5000)
    summary = get_observability_summary()
    assert abs(time.time() - summary["timestamp"]) < 60


def test_timestamp_survives_the_snapshot_roundtrip(tmp_path):
    record_content_quality(returned_chars=5000)
    target = tmp_path / "live_report.json"
    write_snapshot(target)
    restored = read_snapshot(target)
    assert "timestamp" in restored
    assert abs(time.time() - restored["timestamp"]) < 60


def test_aggregator_parses_the_snapshot_timestamp():
    mod = _aggregator()
    record_content_quality(returned_chars=5000)
    parsed = mod._parse_report_time(get_observability_summary())
    assert parsed is not None
    assert abs(parsed.timestamp() - time.time()) < 60


# --- Window arithmetic -------------------------------------------------


def _report(days_ago: float, usable: int, total: int = 100) -> dict:
    return {
        "timestamp": time.time() - days_ago * 86400,
        "content_quality": {
            "fetches": total,
            "usable": usable,
            "thin": total - usable,
            "empty": 0,
            "truncated_by_output_limit": 0,
        },
    }


def test_old_reports_fall_outside_the_7d_window():
    """The point of a rolling window: stale data stops counting."""
    mod = _aggregator()
    reports = [_report(0, 95), _report(3, 90), _report(10, 50), _report(40, 10)]

    seven = mod.aggregate_slo_metrics(reports, 7)
    assert seven["content_quality"]["reports_with_data"] == 2, "current + 3 days ago"

    thirty = mod.aggregate_slo_metrics(reports, 30)
    assert thirty["content_quality"]["reports_with_data"] == 3, "current + 3d + 10d; 40d excluded"


def test_window_rates_use_only_in_window_reports():
    """A 40-day-old bad run must not drag down the 7d number."""
    mod = _aggregator()
    reports = [_report(0, 100), _report(40, 0)]
    seven = mod.aggregate_slo_metrics(reports, 7)
    assert seven["content_quality"]["usable_rate"] == 100.0


def test_without_a_timestamp_a_report_is_counted_everywhere():
    """Documents the old failure mode so the timestamp cannot be dropped again."""
    mod = _aggregator()
    legacy = {"content_quality": {"fetches": 100, "usable": 50, "thin": 50, "empty": 0}}
    assert mod._parse_report_time(legacy) is None
    for days in (7, 30):
        assert mod.aggregate_slo_metrics([legacy], days)["content_quality"]["reports_with_data"] == 1


# --- History layout ----------------------------------------------------


def test_history_directory_is_discovered_recursively(tmp_path):
    """CI stores one directory per run; the loader must find them.

    The aggregator globs for files literally named live_report.json, so the
    history branch layout is runs/<run-id>/live_report.json rather than a flat
    runs/<run-id>.json - a flat layout would be invisible to it.
    """
    mod = _aggregator()
    for idx, days in enumerate((0, 1, 2)):
        run_dir = tmp_path / "history" / f"run{idx}"
        run_dir.mkdir(parents=True)
        (run_dir / "live_report.json").write_text(json.dumps(_report(days, 90)), encoding="utf-8")

    reports = mod.load_live_reports(tmp_path)
    assert len(reports) == 3
    assert all("_source_file" in r for r in reports)


def test_flat_json_files_are_not_discovered(tmp_path):
    """Pins why the layout is nested: a flat file is skipped silently."""
    mod = _aggregator()
    (tmp_path / "run1.json").write_text(json.dumps(_report(1, 90)), encoding="utf-8")
    assert mod.load_live_reports(tmp_path) == []
