"""v1.5.0 Phase 2.1.2 PART A — Advisor Error Integrity tests.

Deterministic, hermetic, offline. Covers the 8 acceptance scenarios:

 1  timeout row (GT=True, decision False, prob 0.0, error "timeout"):
    tp=tn=fp=fn=0, brier None, verified_labels_missing_prediction=1,
    error_records=1, advisor_prediction_coverage=0.0
 2  same timeout row PLUS one valid GT=True prob 0.9 row: Brier == 0.01 and
    tp=1 (timeout excluded)
 3  malformed_response row excluded identically; is_valid_jev_prediction False
 4  valid prob 0.0 / decision False / error None with GT=False: tn=1,
    accuracy 1.0, Brier 0.0, counted in valid_predictions; helper True
 5  100 distinct result_relevant malformed rows -> search relevance stats count 0
    and >=100 gate False; 100 valid prob-0.0 error-None rows -> count 100, gate
    True
 6  duplicate older valid (ts=1, prob .8) + newer error (ts=2, timeout) ->
    index keeps the valid row (prob .8, error None)
 7  two valid rows (ts1 .2, ts2 .8) -> .8 wins; two error rows -> newest kept
    and still invalid
15  objective_outcome result_relevant + matching valid jev row + real event:
    rows["result_relevant"] empty and stats invalid_ground_truth_source == 1
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from webscout_mcp.advisor_evaluator import (
    build_jev_prediction_index,
    evaluate_question,
    is_valid_labeled_prediction,
    join_labeled_rows,
)
from webscout_mcp.jev_store import is_valid_jev_prediction
from webscout_mcp.replay_case import ReplayCase

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "run_objective_evaluation", REPO / "scripts" / "run_objective_evaluation.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Fixtures / row builders
# ---------------------------------------------------------------------------


def _jev(
    trace: str,
    question: str,
    *,
    prob: float | None,
    decision: bool | None,
    error: str | None,
    ts: float = 1.0,
    run: str = "R",
    position: int | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run,
        "trace_id": trace,
        "jev_question": question,
        "position": position,
        "jev_probability": prob,
        "jev_decision": decision,
        "jev_error": error,
        "rule_decision": None,
        "timestamp": ts,
    }


def _rc(
    trace: str,
    expected: str,
    question: str,
    *,
    source: str = "human_verified",
    position: int | None = None,
    run: str = "R",
) -> ReplayCase:
    ctx: dict[str, Any] = {"position": position} if position is not None else {}
    return ReplayCase(
        case_id=f"{run}:{trace}:{question}",
        run_id=run,
        trace_id=trace,
        domain="search" if question == "result_relevant" else "fetch",
        input_features={"question": question, "context": ctx},
        expected_label=expected,
        label_source=source,
    )


def _events(*traces: str) -> list[dict[str, Any]]:
    return [{"run_id": "R", "trace_id": t} for t in traces]


# ===========================================================================
# 1. timeout row -> all confusion zero, missing prediction, coverage 0.0
# ===========================================================================


def test_01_timeout_row_excluded_from_all_metrics():
    jev_rows = [_jev("T", "needs_escalation", prob=0.0, decision=False, error="timeout")]
    cases = [_rc("T", "semantic/needs_more_content", "needs_escalation")]
    res = join_labeled_rows(_events("T"), jev_rows, cases, "R")
    m = evaluate_question("needs_escalation", res.rows["needs_escalation"])

    assert m.tp == m.tn == m.fp == m.fn == 0
    assert m.brier is None
    assert m.n_labeled == 1
    assert m.verified_labels_with_valid_prediction == 0
    assert m.verified_labels_missing_prediction == 1
    assert m.valid_predictions == 0
    assert m.error_records == 1
    assert m.advisor_prediction_coverage == 0.0


# ===========================================================================
# 2. timeout + one valid GT=True prob 0.9 -> Brier 0.01, tp=1
# ===========================================================================


def test_02_timeout_excluded_valid_counts():
    jev_rows = [
        _jev("T1", "needs_escalation", prob=0.0, decision=False, error="timeout", ts=1.0),
        _jev("T2", "needs_escalation", prob=0.9, decision=True, error=None, ts=1.0),
    ]
    cases = [
        _rc("T1", "semantic/needs_more_content", "needs_escalation"),
        _rc("T2", "semantic/needs_more_content", "needs_escalation"),
    ]
    res = join_labeled_rows(_events("T1", "T2"), jev_rows, cases, "R")
    m = evaluate_question("needs_escalation", res.rows["needs_escalation"])

    assert m.tp == 1  # only the valid 0.9 row; timeout excluded
    assert m.brier == round((0.9 - 1.0) ** 2, 5)  # 0.01
    assert m.n_labeled == 2
    assert m.verified_labels_with_valid_prediction == 1
    assert m.verified_labels_missing_prediction == 1


# ===========================================================================
# 3. malformed_response excluded identically; helper False
# ===========================================================================


def test_03_malformed_response_excluded_identically():
    raw = {"jev_error": "malformed_response", "jev_probability": 0.0, "jev_decision": False}
    assert is_valid_jev_prediction(raw) is False

    jev_rows = [_jev("T", "result_usable", prob=0.0, decision=False, error="malformed_response")]
    cases = [_rc("T", "semantic/result_not_usable", "result_usable")]
    res = join_labeled_rows(_events("T"), jev_rows, cases, "R")
    m = evaluate_question("result_usable", res.rows["result_usable"])

    assert m.tp == m.tn == m.fp == m.fn == 0
    assert m.brier is None
    assert m.verified_labels_missing_prediction == 1
    assert m.error_records == 1


# ===========================================================================
# 4. valid prob 0.0 / decision False / error None with GT=False -> strong NO
# ===========================================================================


def test_04_strong_no_is_a_valid_prediction():
    raw = {"jev_error": None, "jev_probability": 0.0, "jev_decision": False}
    assert is_valid_jev_prediction(raw) is True

    jev_rows = [_jev("T", "result_usable", prob=0.0, decision=False, error=None)]
    cases = [_rc("T", "semantic/result_not_usable", "result_usable")]
    res = join_labeled_rows(_events("T"), jev_rows, cases, "R")
    rows = res.rows["result_usable"]
    assert is_valid_labeled_prediction(rows[0]) is True

    m = evaluate_question("result_usable", rows)
    assert m.tn == 1
    assert m.accuracy == 1.0
    assert m.brier == 0.0
    assert m.valid_predictions == 1
    assert m.error_records == 0
    assert m.verified_labels_with_valid_prediction == 1


# ===========================================================================
# 5. 100 malformed result_relevant rows -> count 0 / gate False;
#    100 valid prob-0.0 error-None rows -> count 100 / gate True
# ===========================================================================


def test_05_malformed_rows_not_predictions_valid_rows_are():
    malformed = [
        _jev(f"t{i}", "result_relevant", prob=0.0, decision=False, error="malformed_response", ts=float(i))
        for i in range(100)
    ]
    n_bad, _, _ = cli._search_relevance_prediction_stats(malformed)
    assert n_bad == 0
    assert not (n_bad >= 100)  # >=100 gate is False

    valid = [_jev(f"t{i}", "result_relevant", prob=0.0, decision=False, error=None, ts=float(i)) for i in range(100)]
    n_ok, _, keys = cli._search_relevance_prediction_stats(valid)
    assert n_ok == 100
    assert n_ok >= 100  # >=100 gate is True
    assert len(keys) == 100


# ===========================================================================
# 6. older valid (ts=1, prob .8) beats newer error (ts=2, timeout)
# ===========================================================================


def test_06_older_valid_beats_newer_error():
    rows = [
        _jev("T", "needs_escalation", prob=0.8, decision=True, error=None, ts=1.0),
        _jev("T", "needs_escalation", prob=0.0, decision=False, error="timeout", ts=2.0),
    ]
    index, dupes = build_jev_prediction_index(rows)
    assert dupes == 1
    kept = index[("R", "T", "needs_escalation")]
    assert kept["jev_probability"] == 0.8
    assert kept["jev_error"] is None
    assert is_valid_jev_prediction(kept) is True


# ===========================================================================
# 7. same validity -> newest ts wins; two errors -> newest kept, still invalid
# ===========================================================================


def test_07_same_validity_newest_timestamp_wins():
    valid_rows = [
        _jev("T", "needs_escalation", prob=0.2, decision=False, error=None, ts=1.0),
        _jev("T", "needs_escalation", prob=0.8, decision=True, error=None, ts=2.0),
    ]
    index, _ = build_jev_prediction_index(valid_rows)
    assert index[("R", "T", "needs_escalation")]["jev_probability"] == 0.8

    err_rows = [
        _jev("T", "needs_escalation", prob=0.0, decision=False, error="timeout", ts=1.0),
        _jev("T", "needs_escalation", prob=0.0, decision=False, error="malformed_response", ts=2.0),
    ]
    index2, _ = build_jev_prediction_index(err_rows)
    kept = index2[("R", "T", "needs_escalation")]
    assert kept["jev_error"] == "malformed_response"  # newest error kept
    assert is_valid_jev_prediction(kept) is False


# ===========================================================================
# 15. objective_outcome result_relevant -> human-only defense, no rows emitted
# ===========================================================================


def test_15_objective_result_relevant_is_rejected():
    jev_rows = [_jev("T", "result_relevant", prob=0.9, decision=True, error=None, position=1)]
    cases = [
        _rc(
            "T",
            "semantic/result_relevant",
            "result_relevant",
            source="objective_outcome",
            position=1,
        )
    ]
    res = join_labeled_rows(_events("T"), jev_rows, cases, "R")
    assert res.rows["result_relevant"] == []
    assert res.stats["result_relevant"]["invalid_ground_truth_source"] == 1
