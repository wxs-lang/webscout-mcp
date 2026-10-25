"""Tests for observability snapshot persistence.

Counters live in process memory. For their numbers to reach any report — the
SLO aggregator reads JSON files from disk, not live processes — a run has to
leave a snapshot behind. These tests pin that path, including the failure modes
that must degrade quietly instead of breaking a reporting job.
"""

from __future__ import annotations

import json

import pytest

from webscout_mcp.observability import (
    read_snapshot,
    record_content_quality,
    reset_for_tests,
    write_snapshot,
)


@pytest.fixture(autouse=True)
def _clean():
    reset_for_tests()
    yield
    reset_for_tests()


def test_snapshot_roundtrip_preserves_content_quality(tmp_path):
    record_content_quality(returned_chars=5000, backend="fast-http", status="success")
    record_content_quality(returned_chars=40, backend="fast-http", status="success")
    record_content_quality(returned_chars=0, backend="crawl4ai", status="failed")

    target = tmp_path / "live_report.json"
    written = write_snapshot(target)

    assert target.exists()
    restored = read_snapshot(target)
    assert restored == json.loads(target.read_text(encoding="utf-8"))
    assert restored["content_quality"]["fetches"] == 3
    assert restored["content_quality"]["usable"] == 1
    assert restored["content_quality"]["thin"] == 1
    assert restored["content_quality"]["empty"] == 1
    assert restored["content_quality"] == written["content_quality"]


def test_snapshot_includes_the_other_counter_families(tmp_path):
    """The snapshot is the whole summary, not just content quality."""
    target = tmp_path / "live_report.json"
    write_snapshot(target)
    restored = read_snapshot(target)
    for key in (
        "started_at",
        "backends",
        "escalations",
        "ssrf_blocks",
        "recovery_reasons",
        "recovery_actions",
        "continuation",
        "crawl",
        "content_quality",
    ):
        assert key in restored, key


def test_snapshot_creates_missing_parent_directories(tmp_path):
    target = tmp_path / "nested" / "deeper" / "live_report.json"
    write_snapshot(target)
    assert target.exists()


def test_snapshot_write_leaves_no_temp_file_behind(tmp_path):
    target = tmp_path / "live_report.json"
    write_snapshot(target)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_snapshot_does_not_echo_page_content(tmp_path):
    """A marker passed through a metric must never reach the file as content."""
    marker = "SNAPSHOT-SECRET-MARKER"
    record_content_quality(returned_chars=len(marker), status="success")
    target = tmp_path / "live_report.json"
    write_snapshot(target)
    assert marker not in target.read_text(encoding="utf-8")


def test_read_missing_snapshot_returns_none(tmp_path):
    assert read_snapshot(tmp_path / "absent.json") is None


def test_read_corrupt_snapshot_returns_none_instead_of_raising(tmp_path):
    target = tmp_path / "live_report.json"
    target.write_text("{ this is not json", encoding="utf-8")
    assert read_snapshot(target) is None


def test_read_non_object_snapshot_returns_none(tmp_path):
    """A JSON array is valid JSON but not a snapshot."""
    target = tmp_path / "live_report.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")
    assert read_snapshot(target) is None


def test_write_snapshot_returns_the_same_snapshot_it_persists(tmp_path):
    record_content_quality(returned_chars=1000, backend="fast-http", status="success")
    target = tmp_path / "live_report.json"
    returned = write_snapshot(target)
    assert read_snapshot(target) == returned


def test_snapshot_overwrites_atomically_on_repeat_writes(tmp_path):
    target = tmp_path / "live_report.json"
    record_content_quality(returned_chars=5000)
    write_snapshot(target)
    first = read_snapshot(target)["content_quality"]["fetches"]

    record_content_quality(returned_chars=5000)
    write_snapshot(target)
    second = read_snapshot(target)["content_quality"]["fetches"]

    assert (first, second) == (1, 2)
