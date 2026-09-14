"""Regression tests for scripts/slo_aggregator.py.

Guards against the timestamp-parsing bug where a float epoch timestamp
(written by tests/live/test_live_search.py via ``time.time()``) crashed
aggregation with ``AttributeError: 'float' object has no attribute 'replace'``,
while the workflow's ``|| echo`` swallowed the failure (green CI, broken
monitoring).
"""

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import slo_aggregator as sa


def _sample_report(timestamp=None):
    return {
        "timestamp": timestamp if timestamp is not None else time.time(),
        "search_stats": {
            "total": 5,
            "successful": 5,
            "failed": 0,
            "latencies_ms": [400, 500, 600, 700, 800],
            "fallback_count": 0,
            "fallback_rate": 0.0,
            "error_types": {},
            "providers": {"bing": 5},
        },
        "fetch_stats": {
            "total": 3,
            "successful": 3,
            "failed": 0,
            "latencies_ms": [900, 1000, 1100],
            "error_types": {},
            "providers": {"direct": 3},
        },
    }


def _current_layout_report(timestamp=None):
    """Report in the layout written by tests/live/test_live_search.py."""
    return {
        "timestamp": timestamp if timestamp is not None else time.time(),
        "datetime": "2026-09-13 04:33:20",
        "search": {
            "count": 40,
            "success_count": 40,
            "failure_count": 0,
            "success_rate": 100.0,
            "p50_latency_ms": 162.7,
            "p95_latency_ms": 271.0,
            "avg_latency_ms": 182.3,
            "error_types": {},
            "providers": {"bing": 39, "duckduckgo": 1},
        },
        "fetch": {
            "count": 10,
            "success_count": 10,
            "failure_count": 0,
            "success_rate": 100.0,
            "p50_latency_ms": 370.2,
            "p95_latency_ms": 875.1,
            "avg_latency_ms": 417.7,
            "error_types": {},
            "providers": {"WebScout Fetcher (status=200)": 10},
        },
        "fallback": {
            "count": 2,
            "success_count": 2,
            "failure_count": 0,
            "success_rate": 100.0,
            "p50_latency_ms": 675.6,
            "p95_latency_ms": 675.6,
            "avg_latency_ms": 415.6,
            "error_types": {},
            "providers": {"duckduckgo": 1, "all": 1},
        },
    }


class TestParseReportTime:
    def test_float_epoch_timestamp(self):
        """The real-world format written by test_live_search.py."""
        ts = time.time()
        parsed = sa._parse_report_time({"timestamp": ts})
        assert parsed is not None
        assert parsed.tzinfo is not None
        assert abs(parsed.timestamp() - ts) < 1

    def test_int_epoch_timestamp(self):
        parsed = sa._parse_report_time({"timestamp": int(time.time())})
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_iso_string_with_z(self):
        iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        parsed = sa._parse_report_time({"timestamp": iso})
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_naive_iso_string(self):
        parsed = sa._parse_report_time(
            {"timestamp": datetime.now().isoformat()}
        )
        assert parsed is not None
        # Naive timestamps are assumed to be UTC
        assert parsed.tzinfo is not None

    def test_numeric_string_epoch(self):
        parsed = sa._parse_report_time(
            {"timestamp": str(time.time())}
        )
        assert parsed is not None

    def test_run_time_fallback(self):
        parsed = sa._parse_report_time(
            {"run_time": time.time()}
        )
        assert parsed is not None

    def test_missing_timestamp_returns_none(self):
        assert sa._parse_report_time({}) is None
        assert sa._parse_report_time({"timestamp": ""}) is None
        assert sa._parse_report_time({"timestamp": None}) is None

    def test_invalid_timestamp_raises_value_error(self):
        with pytest.raises(ValueError):
            sa._parse_report_time({"timestamp": "not-a-date"})

    def test_unsupported_type_raises_value_error(self):
        with pytest.raises(ValueError):
            sa._parse_report_time({"timestamp": {"nested": True}})


class TestAggregateSloMetrics:
    def test_float_timestamp_reports_aggregated(self):
        """Regression: float timestamps must not crash aggregation."""
        reports = [
            _sample_report(time.time()),
            _sample_report(time.time() - 3600),
        ]
        result = sa.aggregate_slo_metrics(reports, 7)
        assert result["status"] == "healthy"
        assert result["data_points"] == 2
        assert result["search"]["success_rate"] == 100.0
        assert result["fetch"]["success_rate"] == 100.0

    def test_current_layout_report_aggregated(self):
        """Regression: the real layout (count/success_count/percentiles)
        must produce 100% rates, not 0% (the silent false-green bug)."""
        reports = [_current_layout_report(time.time())]
        result = sa.aggregate_slo_metrics(reports, 7)
        assert result["status"] == "healthy"
        assert result["data_points"] == 1
        assert result["search"]["total"] == 40
        assert result["search"]["successful"] == 40
        assert result["search"]["success_rate"] == 100.0
        assert result["fetch"]["total"] == 10
        assert result["fetch"]["success_rate"] == 100.0
        # Percentiles come from the reported p50/p95 when no raw array exists
        assert result["search"]["latency_p50_ms"] == 162.7
        assert result["search"]["latency_p95_ms"] == 271.0
        assert result["fetch"]["latency_p95_ms"] == 875.1
        # Fallback counted from the top-level fallback section
        assert result["search"]["fallback_count"] == 2

    def test_mixed_layout_reports(self):
        reports = [
            _sample_report(time.time()),          # legacy layout
            _current_layout_report(time.time()),  # current layout
        ]
        result = sa.aggregate_slo_metrics(reports, 7)
        assert result["data_points"] == 2
        assert result["search"]["total"] == 45  # 5 + 40
        assert result["search"]["successful"] == 45
        assert result["search"]["success_rate"] == 100.0

    def test_mixed_timestamp_formats(self):
        reports = [
            _sample_report(time.time()),  # float
            _sample_report(
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            ),  # ISO Z
            _sample_report(datetime.now().isoformat()),  # naive ISO
            _sample_report(""),  # legacy: no usable timestamp
        ]
        result = sa.aggregate_slo_metrics(reports, 7)
        # The legacy empty-timestamp report is included best-effort
        assert result["data_points"] == 4

    def test_old_reports_excluded_by_window(self):
        old = _sample_report(time.time() - 30 * 86400)
        fresh = _sample_report(time.time())
        result = sa.aggregate_slo_metrics([old, fresh], 7)
        assert result["data_points"] == 1

    def test_invalid_timestamp_fails_loudly(self):
        """Data/code errors must raise, not be silently included."""
        reports = [_sample_report("garbage-timestamp")]
        with pytest.raises(ValueError):
            sa.aggregate_slo_metrics(reports, 7)

    def test_no_data(self):
        result = sa.aggregate_slo_metrics([], 7)
        assert result["status"] == "no_data"
        assert result["data_points"] == 0


class TestGenerateSloReport:
    def test_full_report_generation(self, tmp_path):
        result_dir = tmp_path / "live-test-results"
        result_dir.mkdir()
        (result_dir / "live_report.json").write_text(
            __import__("json").dumps(_sample_report(time.time()))
        )

        reports = sa.load_live_reports(result_dir)
        assert len(reports) == 1

        output_dir = tmp_path / "slo-reports"
        report = sa.generate_slo_report(reports, output_dir)
        assert report["overall_status"] == "healthy"
        assert (output_dir / "slo_report.json").exists()
        assert (output_dir / "SLO_DASHBOARD.md").exists()

    def test_load_ignores_corrupt_json(self, tmp_path):
        result_dir = tmp_path / "live-test-results"
        result_dir.mkdir()
        (result_dir / "live_report.json").write_text("{ not valid json")
        reports = sa.load_live_reports(result_dir)
        assert reports == []
