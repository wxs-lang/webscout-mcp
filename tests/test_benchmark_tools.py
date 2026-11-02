"""The benchmark script must stay runnable, and must actually catch a regression.

A benchmark that always reports 100% is worse than none: it manufactures confidence. So
alongside a smoke test that the script runs, there is a test that deliberately breaks one
behaviour and asserts the benchmark notices.

The regression used is the v2.1 defect itself - a monitor that does not persist its
baseline. Reproducing it here proves the scenario is load-bearing rather than decorative.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "benchmark_tools.py"


def _run_benchmark(tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--strict", "--json", str(out)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO),
    )
    assert proc.returncode == 0, f"benchmark failed\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
    return json.loads(out.read_text(encoding="utf-8"))


def test_benchmark_script_runs_and_passes():
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    assert report["failed"] == 0, report["scenarios"]
    assert report["total"] >= 12, report["total"]
    assert report["pass_rate"] == 100.0


def test_every_scenario_states_what_it_proves():
    """A scenario whose name is the only description cannot explain a failure."""
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    for scenario in report["scenarios"]:
        assert scenario["proves"], f"{scenario['name']} has no description"
        assert len(scenario["proves"]) > 10, scenario


def test_skips_carry_a_reason():
    """Skipping silently would let coverage quietly shrink."""
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    for entry in report["skipped"]:
        assert entry["reason"], f"{entry['name']} skipped without a reason"
        assert len(entry["reason"]) > 20, entry


def test_the_benchmark_catches_a_broken_baseline(tmp_path):
    """Break persistence the way v2.1 was broken, and confirm the scenario fails.

    `_save_history` is what carries the comparison baseline to disk. Making it a no-op
    reproduces the original defect: a fresh process starts with no baseline, so no change
    can ever be reported. If the benchmark still passes, its persistence scenario is
    decorative.
    """
    shim = tmp_path / "run_broken.py"
    report = tmp_path / "report.json"
    shim.write_text(
        "import runpy, sys\n"
        "from webscout_mcp.extras.monitor import WebMonitor\n"
        "WebMonitor._save_history = lambda self: None\n"
        f"sys.argv = [{str(SCRIPT)!r}, '--strict', '--json', {str(report)!r}]\n"
        f"runpy.run_path({str(SCRIPT)!r}, run_name='__main__')\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(shim)],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO),
        env={**__import__("os").environ, "PYTHONPATH": str(REPO)},
    )
    assert proc.returncode == 1, (
        "the benchmark passed even though the monitor no longer persists its baseline; "
        f"the persistence scenario is not load-bearing\nstdout:\n{proc.stdout[-1500:]}"
    )
    assert "web_monitor" in proc.stdout, proc.stdout[-1500:]
    assert report.exists(), "a failing run should still write its report"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["failed"] >= 1, data
    assert any("web_monitor" in s["name"] for s in data["scenarios"] if not s["passed"]), data


def test_report_shape_is_stable():
    """The JSON is consumed by CI and by humans; its keys should not drift silently."""
    import tempfile

    report = _run_benchmark(pathlib.Path(tempfile.mkdtemp()))
    assert set(report) == {"total", "passed", "failed", "pass_rate", "scenarios", "skipped"}
    for scenario in report["scenarios"]:
        assert set(scenario) == {"name", "passed", "proves", "detail", "error"}
