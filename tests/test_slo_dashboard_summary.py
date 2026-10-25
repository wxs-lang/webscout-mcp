"""The CI summary must not print junk for a window with no observations.

slo_dashboard_summary.py formats the aggregator output into the GitHub step
summary. After the aggregator started reporting None for "no observations", the
summary printed:

    - Search Success: **None%**
    - Search P95: N/Ams

The first is a Python repr leaking into a dashboard; the second appends a unit
to a placeholder. Worse than ugly: both make missing data look like a measured
value, which is the same confusion the aggregator change was meant to remove.
"""

from __future__ import annotations

import json

import pytest


def _run_summary(tmp_path, report: dict) -> str:
    """Invoke the summary script in a temp cwd and return its stdout."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    (tmp_path / "slo-reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "slo-reports" / "slo_report.json").write_text(json.dumps(report), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts" / "slo_dashboard_summary.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout.decode("utf-8", "replace")


def _window(status: str, *, rate, p95, usable, with_data: int) -> dict:
    return {
        "status": status,
        "search": {"success_rate": rate, "latency_p95_ms": p95},
        "fetch": {"success_rate": rate},
        "content_quality": {"usable_rate": usable, "reports_with_data": with_data},
    }


def _report(status: str, window: dict) -> dict:
    return {"overall_status": status, "slo_7d": window, "slo_30d": window}


# --- No data -----------------------------------------------------------


def test_no_data_window_prints_a_phrase_not_a_repr(tmp_path):
    out = _run_summary(tmp_path, _report("no_data", _window("no_data", rate=None, p95=None, usable=None, with_data=0)))
    assert "None%" not in out, "a Python repr leaked into the dashboard"
    assert "N/A (no data)" in out


def test_no_data_window_does_not_append_a_unit_to_the_placeholder(tmp_path):
    out = _run_summary(tmp_path, _report("no_data", _window("no_data", rate=None, p95=None, usable=None, with_data=0)))
    assert "N/Ams" not in out


def test_no_data_window_reports_zero_reports_with_data(tmp_path):
    out = _run_summary(tmp_path, _report("no_data", _window("no_data", rate=None, p95=None, usable=None, with_data=0)))
    assert "(0 report(s) with data)" in out


# --- Real data ---------------------------------------------------------


def test_real_rates_are_printed_with_their_unit(tmp_path):
    out = _run_summary(
        tmp_path, _report("healthy", _window("healthy", rate=99.5, p95=720.0, usable=100.0, with_data=7))
    )
    assert "99.5%" in out
    assert "720.0ms" in out
    assert "100.0%" in out
    assert "(7 report(s) with data)" in out


def test_both_windows_are_rendered(tmp_path):
    report = {
        "overall_status": "healthy",
        "slo_7d": _window("healthy", rate=100.0, p95=500.0, usable=100.0, with_data=4),
        "slo_30d": _window("warning", rate=98.0, p95=900.0, usable=95.0, with_data=30),
    }
    out = _run_summary(tmp_path, report)
    assert "### 7-Day SLO" in out
    assert "### 30-Day SLO" in out
    assert "98.0%" in out
    assert "900.0ms" in out


def test_missing_content_quality_block_does_not_crash(tmp_path):
    """Older reports have no content_quality window; the summary must cope."""
    window = {"status": "healthy", "search": {"success_rate": 100.0}, "fetch": {"success_rate": 100.0}}
    out = _run_summary(tmp_path, {"overall_status": "healthy", "slo_7d": window, "slo_30d": window})
    assert "N/A (no data)" in out


def test_overall_status_is_shown_uppercased(tmp_path):
    out = _run_summary(
        tmp_path, _report("violating", _window("violating", rate=0.0, p95=100.0, usable=0.0, with_data=1))
    )
    assert "VIOLATING" in out


def test_missing_report_file_exits_zero(tmp_path):
    """No report yet is not a failure - the aggregator may not have run."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "slo_dashboard_summary.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 0
    assert "No SLO report generated" in proc.stdout.decode("utf-8", "replace")
