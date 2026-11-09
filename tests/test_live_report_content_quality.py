"""The live test report must carry content-quality counters.

The counters live in process memory inside ``webscout_mcp.observability``. If
``LiveTestReport.to_dict()`` omits them, the report on disk has no quality data
and the SLO aggregator can only ever report ``no_data`` for it — which is the
state this report was in. These tests pin the injection and its failure mode.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LIVE_TEST = REPO / "tests" / "live" / "test_live_search.py"


def _load_to_dict_source() -> str:
    """Extract LiveTestReport.to_dict source without importing the module.

    Importing the live module runs pytest fixtures and network setup, so the
    source is inspected directly instead.
    """
    tree = ast.parse(LIVE_TEST.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "LiveTestReport":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "to_dict":
                    return ast.get_source_segment(LIVE_TEST.read_text(encoding="utf-8"), item) or ""
    raise AssertionError("LiveTestReport.to_dict not found")


def test_to_dict_injects_content_quality():
    src = _load_to_dict_source()
    assert "content_quality" in src, "to_dict must attach the content-quality block"
    assert "get_observability_summary" in src


def test_injection_is_wrapped_so_reporting_cannot_fail_the_run():
    """A reporting bug must never turn a live test run red."""
    src = _load_to_dict_source()
    idx = src.find("content_quality")
    assert idx != -1
    assert "except Exception" in src[idx - 400 : idx + 400]


def test_injection_reads_from_the_real_summary():
    """Exercise the same call the report makes, against real counters."""
    from webscout_mcp.observability import (
        get_observability_summary,
        record_content_quality,
        reset_for_tests,
    )

    reset_for_tests()
    try:
        record_content_quality(returned_chars=5000, backend="fast-http", status="success")
        record_content_quality(returned_chars=3000, backend="fast-http", status="success")
        record_content_quality(returned_chars=50, backend="fast-http", status="success")

        block = get_observability_summary().get("content_quality", {})
        assert block["fetches"] == 3
        assert block["usable"] == 2
        assert block["thin"] == 1
        assert block["usable_rate"] == pytest.approx(0.6667, abs=1e-4)
    finally:
        reset_for_tests()


def test_report_with_injected_quality_reaches_the_aggregator(monkeypatch):
    """End to end: counters -> report dict -> SLO verdict."""
    import sys
    import time

    sys.path.insert(0, str(REPO / "scripts"))
    from slo_aggregator import aggregate_slo_metrics

    from webscout_mcp.observability import (
        get_observability_summary,
        record_content_quality,
        reset_for_tests,
    )

    reset_for_tests()
    try:
        record_content_quality(returned_chars=5000, status="success")
        record_content_quality(returned_chars=40, status="success")

        report = {
            "timestamp": time.time(),
            "search": {"count": 1, "success_count": 1},
            "fetch": {"count": 2, "success_count": 2},
            "content_quality": get_observability_summary().get("content_quality", {}),
        }
        result = aggregate_slo_metrics([report], 7)
        assert result["content_quality"]["status"] == "measured"
        assert result["content_quality"]["usable_rate"] == 50.0
        assert result["status"] == "violating"
    finally:
        reset_for_tests()


def test_a_report_without_the_block_is_no_data_not_zero():
    """The pre-change report shape must degrade to no_data."""
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    import time

    from slo_aggregator import aggregate_slo_metrics

    report = {
        "timestamp": time.time(),
        "search": {"count": 1, "success_count": 1},
        "fetch": {"count": 1, "success_count": 1},
    }
    result = aggregate_slo_metrics([report], 7)
    assert result["content_quality"]["status"] == "no_data"
    assert result["content_quality"]["usable_rate"] is None
