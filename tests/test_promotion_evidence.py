"""F4 must be measured, not asserted.

REFACTOR_PLAN.md requires 30 days of live tests for Beta -> Stable.
MODULE_STATUS.md declares nine tools Stable. Live-test history starts 2026-10-25,
so the claim runs ahead of the evidence by design - the tools shipped and users
depend on them, which is why this reports rather than fails.

These tests keep the measurement honest: it must read the declared levels rather
than a second hardcoded list, count days rather than runs, and survive the CI
environment where GITHUB_STEP_SUMMARY is usually unset.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_promotion_evidence as checker  # noqa: E402

# --- Reading the declared levels ---------------------------------------


def _status_doc(tmp_path: Path, rows: list[tuple[str, str]]) -> Path:
    lines = ["# Module Status", "", "| Tool | Category | Stability | Description |", "|---|---|---|---|"]
    for name, level in rows:
        lines.append(f"| `{name}` | Cat | {level} | Desc |")
    path = tmp_path / "MODULE_STATUS.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_reads_stable_tools_from_the_status_doc(tmp_path):
    doc = _status_doc(
        tmp_path,
        [("web_search", "✅ Stable"), ("web_fetch", "✅ Stable"), ("content_quality", "🧪 Experimental")],
    )
    assert checker.stable_tools(doc) == ["web_fetch", "web_search"]


def test_experimental_tools_are_not_counted_as_stable(tmp_path):
    doc = _status_doc(tmp_path, [("broken_links", "🧪 Experimental")])
    assert checker.stable_tools(doc) == []


def test_missing_status_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        checker.stable_tools(tmp_path / "nope.md")


def test_the_real_status_doc_declares_nine_stable_tools():
    """Pins the current claim. If a tool is promoted or demoted, this changes
    deliberately rather than the check silently measuring a different set."""
    names = checker.stable_tools(REPO / "MODULE_STATUS.md")
    assert len(names) == 9
    assert "web_search" in names and "web_fetch" in names


# --- Counting evidence days --------------------------------------------


def _run(tmp_path: Path, stamp: str) -> None:
    run_dir = tmp_path / "runs" / f"12345-{stamp}" / "live_report.json"
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    run_dir.write_text(json.dumps({"timestamp": 0}), encoding="utf-8")


def test_days_are_taken_from_the_run_directory(tmp_path):
    _run(tmp_path, "20261025T062643Z")
    _run(tmp_path, "20261026T042814Z")
    days = checker.report_days(tmp_path)
    assert [d.strftime("%Y%m%d") for d in days] == ["20261025", "20261026"]


def test_three_runs_in_one_day_are_one_day_of_evidence(tmp_path):
    _run(tmp_path, "20261025T062643Z")
    _run(tmp_path, "20261025T072925Z")
    _run(tmp_path, "20261025T080542Z")
    assert len(checker.report_days(tmp_path)) == 1


def test_days_are_sorted_and_unique(tmp_path):
    _run(tmp_path, "20261027T044708Z")
    _run(tmp_path, "20261025T062643Z")
    _run(tmp_path, "20261025T072925Z")
    days = checker.report_days(tmp_path)
    assert [d.strftime("%Y%m%d") for d in days] == ["20261025", "20261027"]


def test_falls_back_to_the_report_timestamp(tmp_path):
    """A directory without the expected stamp must still contribute, or a
    renamed run would silently reduce the evidence count."""
    weird = tmp_path / "runs" / "unusual-name" / "live_report.json"
    weird.parent.mkdir(parents=True, exist_ok=True)
    weird.write_text(json.dumps({"timestamp": 1792918467}), encoding="utf-8")
    assert len(checker.report_days(tmp_path)) == 1


def test_missing_history_dir_yields_no_days(tmp_path):
    assert checker.report_days(tmp_path / "absent") == []


def test_unparseable_report_does_not_crash(tmp_path):
    weird = tmp_path / "runs" / "odd" / "live_report.json"
    weird.parent.mkdir(parents=True, exist_ok=True)
    weird.write_text("{not json", encoding="utf-8")
    assert checker.report_days(tmp_path) == []


# --- The verdict -------------------------------------------------------


def test_shortfall_is_reported_and_does_not_fail_by_default(tmp_path, capsys):
    code, out = _runner(tmp_path, capsys, 5)
    assert code == 0, "reporting a known gap must not break the build"
    assert "5 of 30" in out
    assert "25 day(s)" in out


def test_require_flag_turns_the_gap_into_a_failure(tmp_path, capsys):
    code, _ = _runner(tmp_path, capsys, 5, extra=["--require"])
    assert code == 1


def test_require_passes_when_evidence_is_sufficient(tmp_path, capsys):
    code, _ = _runner(tmp_path, capsys, 30, extra=["--require"])
    assert code == 0


def test_enough_days_are_announced(tmp_path, capsys):
    code, out = _runner(tmp_path, capsys, 30)
    assert code == 0
    assert "OK" in out


def _runner(tmp_path, capsys, days, extra=None, required=30):
    doc = _status_doc(tmp_path, [("web_search", "✅ Stable")])
    root = tmp_path / "history"
    # Spread the days out so date arithmetic is not clamped by month length.
    for i in range(days):
        month = 10 + (i // 28)
        day = 1 + (i % 28)
        _run(root, f"2026{month:02d}{day:02d}T060000Z")
    code = checker.main(
        [
            "--status-file",
            str(doc),
            "--history-root",
            str(root),
            "--required-days",
            str(required),
            *(extra or []),
        ]
    )
    return code, capsys.readouterr().out


# --- The CI environment ------------------------------------------------


def test_unset_github_step_summary_does_not_crash(tmp_path, capsys, monkeypatch):
    """It crashed with PermissionError on '.' because Path("") is Path(".")."""
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    code, _ = _runner(tmp_path, capsys, 5)
    assert code == 0


def test_empty_github_step_summary_does_not_crash(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", "")
    code, _ = _runner(tmp_path, capsys, 5)
    assert code == 0


def test_step_summary_is_written_when_set(tmp_path, capsys, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _runner(tmp_path, capsys, 5)
    assert summary.exists()
    text = summary.read_text(encoding="utf-8")
    assert "F4 promotion evidence" in text
    assert "Shortfall" in text
