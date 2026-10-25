"""Tests for the opt-in exit-time snapshot hook and the metrics CLI command.

The hook writes counters that only exist in memory, so it runs exactly once at
process exit and cannot be retried: it has to be correct without a second
chance. These tests drive it through a real subprocess rather than calling the
private callback, because "does atexit actually fire" is the whole question.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from webscout_mcp import observability
from webscout_mcp.observability import (
    enable_snapshot_on_exit,
    has_data,
    read_snapshot,
    record_content_quality,
    reset_for_tests,
    snapshot_on_exit_enabled,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean():
    reset_for_tests()
    yield
    reset_for_tests()


def _run(code: str, cwd: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=120,
    )


def test_has_data_is_false_on_a_fresh_process():
    assert has_data() is False


def test_has_data_turns_true_after_one_fetch():
    record_content_quality(returned_chars=1000, status="success")
    assert has_data() is True


def test_hook_is_off_by_default():
    """Importing the module must not arm any filesystem write."""
    assert snapshot_on_exit_enabled() is False


def test_enable_marks_the_hook_as_armed():
    enable_snapshot_on_exit(Path("somewhere.json"))
    assert snapshot_on_exit_enabled() is True


def test_enable_is_idempotent(tmp_path):
    first = tmp_path / "first.json"
    enable_snapshot_on_exit(first)
    enable_snapshot_on_exit(tmp_path / "second.json")
    # Only one hook is registered, so the first path is the one that survives.
    assert snapshot_on_exit_enabled() is True


def test_exit_hook_writes_a_snapshot_after_real_work(tmp_path):
    """A subprocess that does work must leave a readable report behind."""
    target = tmp_path / "live_report.json"
    code = (
        "from webscout_mcp.observability import enable_snapshot_on_exit, record_content_quality\n"
        f"enable_snapshot_on_exit(r'{target}')\n"
        "record_content_quality(returned_chars=5000, backend='fast-http', status='success')\n"
        "record_content_quality(returned_chars=40, backend='fast-http', status='success')\n"
    )
    proc = _run(code, tmp_path)
    assert proc.returncode == 0, proc.stderr

    assert target.exists(), "exit hook did not write a snapshot"
    snap = json.loads(target.read_text(encoding="utf-8"))
    assert snap["content_quality"]["fetches"] == 2
    assert snap["content_quality"]["usable_rate"] == 0.5


def test_exit_hook_skips_a_run_with_no_data(tmp_path):
    """No requests served means no file, not a file full of zeroes."""
    target = tmp_path / "live_report.json"
    code = f"from webscout_mcp.observability import enable_snapshot_on_exit\nenable_snapshot_on_exit(r'{target}')\n"
    proc = _run(code, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert not target.exists(), "an empty run must not produce a zeroed snapshot"


def test_exit_hook_does_not_break_a_failing_process(tmp_path):
    """A crash must keep its original exit code even with the hook armed."""
    target = tmp_path / "live_report.json"
    code = (
        "from webscout_mcp.observability import enable_snapshot_on_exit, record_content_quality\n"
        f"enable_snapshot_on_exit(r'{target}')\n"
        "record_content_quality(returned_chars=5000)\n"
        "raise SystemExit(3)\n"
    )
    proc = _run(code, tmp_path)
    assert proc.returncode == 3, proc.stderr
    # The counters were real work, so they are still worth persisting.
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8"))["content_quality"]["usable"] == 1


def test_metrics_snapshot_cli_writes_even_with_no_data(tmp_path):
    """An explicitly requested file must appear; a missing one is harder to debug."""
    target = tmp_path / "live_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    proc = subprocess.run(
        [sys.executable, "-m", "webscout_mcp", "metrics", "snapshot", "--out", str(target)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert target.exists()
    payload = json.loads(proc.stdout)
    assert payload["written"] == str(target)
    assert payload["has_data"] is False


def test_metrics_show_cli_prints_the_summary(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    proc = subprocess.run(
        [sys.executable, "-m", "webscout_mcp", "metrics", "show"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert "content_quality" in payload
    assert payload["content_quality"]["fetches"] == 0


def test_snapshot_from_hook_is_aggregator_readable(tmp_path):
    """The file the hook writes must be loadable by the SLO aggregator."""
    record_content_quality(returned_chars=5000, backend="fast-http", status="success")
    target = tmp_path / "live_report.json"
    observability.write_snapshot(target)

    sys.path.insert(0, str(REPO / "scripts"))
    from slo_aggregator import aggregate_slo_metrics

    snap = read_snapshot(target)
    result = aggregate_slo_metrics([{**snap, "timestamp": snap["started_at"]}], 7)
    assert result["content_quality"]["status"] == "measured"
    assert result["content_quality"]["usable_rate"] == 100.0
