"""v1.5.0 Phase 2.1.1 — Ground Truth & Search Position Integrity tests.

Deterministic, hermetic, offline. Covers the 15 acceptance scenarios:

 1  result_relevant positions 1/2/3 join to their own predictions
    (the merge-blocker scenario)
 2  duplicate Jev position -> latest-by-timestamp chosen + duplicate count
 3  missing browser CF -> needs_escalation ambiguous (missing_browser_counterfactual)
 4  observed browser no-gain -> objective NO
 5  observed browser rescue -> objective YES
 6  browser CF artifact -> materializer joins by source_trace_id
 7  human gate excludes objective labels
 8  human gate counts human_verified only
 9  search result rows != Jev prediction count
10  real gate uses Jev prediction count
11  preflight JEV_ENABLED=false -> BLOCKED
12  report-only missing run DB -> non-zero error
13  human import wrong run_id rejected/skipped
14  result_relevant missing position rejected
15  operation join coverage reported separately from per-result prediction coverage
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from webscout_mcp import decision_store, eval_human, jev_store
from webscout_mcp.advisor_evaluator import (
    build_jev_prediction_index,
    join_labeled_rows,
)
from webscout_mcp.decision_event import DecisionDomain, DecisionEvent, DecisionStage
from webscout_mcp.objective_labeler import (
    has_browser_counterfactual,
    jev_needs_escalation_objective,
    materialize_objective_replay_cases,
)
from webscout_mcp.replay_case import ReplayCase

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "run_objective_evaluation", REPO / "scripts" / "run_objective_evaluation.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def hermetic_stores(tmp_path: Path):
    decision_db = tmp_path / "decision_events.db"
    jev_db = tmp_path / "jev_shadow.db"
    decision_store.configure(str(decision_db))
    jev_store.configure(str(jev_db))
    try:
        yield tmp_path, decision_db, jev_db
    finally:
        decision_store.configure(None)
        jev_store.configure(None)


def _jev_row(run="R", trace="T", question="result_relevant", *, position=None, prob=0.5, ts=1.0):
    return {
        "run_id": run,
        "trace_id": trace,
        "jev_question": question,
        "position": position,
        "jev_probability": prob,
        "jev_decision": bool(prob >= 0.5),
        "rule_decision": None,
        "timestamp": ts,
    }


def _rc(trace="T", *, expected="semantic/result_relevant", position=None, source="human_verified"):
    ctx: dict[str, Any] = {}
    if position is not None:
        ctx["position"] = position
    return ReplayCase(
        case_id=f"human:{trace}:result_relevant:p{position}",
        run_id="R",
        trace_id=trace,
        domain="search",
        input_features={"question": "result_relevant", "context": ctx},
        expected_label=expected,
        label_source=source,
    )


def _fetch_event(run_id, trace_id, *, outcome=None, event_id=None):
    return DecisionEvent(
        event_id=event_id or f"ev-{run_id}-{trace_id}",
        run_id=run_id,
        trace_id=trace_id,
        domain=DecisionDomain.FETCH,
        stage=DecisionStage.FINAL,
        outcome_features=outcome or {},
    )


def _seed_jev_raw(db: Path, row: dict[str, Any]) -> None:
    with sqlite3.connect(str(db)) as c:
        c.execute(
            """INSERT INTO jev_records (
                timestamp, trace_id, operation, jev_question, jev_decision,
                jev_probability, run_id, position)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                row.get("timestamp", time.time()),
                row.get("trace_id", "T"),
                row.get("operation", "search"),
                row.get("jev_question", "result_relevant"),
                1 if (row.get("jev_probability") or 0) >= 0.5 else 0,
                row.get("jev_probability"),
                row.get("run_id", "R"),
                row.get("position"),
            ),
        )


# Primary structurally complete, no browser counterfactual observed.
_PRIMARY_COMPLETE_NO_CF = {
    "status": "success",
    "primary_extraction_success": True,
    "primary_content_chars": 1000,
    "truncated": False,
    "continuation_available": False,
}


# ===========================================================================
# 1. result_relevant positions 1/2/3 join to their own predictions
# ===========================================================================


def test_01_result_relevant_positions_join_to_own_predictions():
    events = [{"run_id": "R", "trace_id": "T"}]
    jev_rows = [
        _jev_row(position=1, prob=0.1, ts=1.0),
        _jev_row(position=2, prob=0.9, ts=2.0),
        _jev_row(position=3, prob=0.2, ts=3.0),
    ]
    cases = [
        _rc(position=1, expected="semantic/result_not_relevant"),
        _rc(position=2, expected="semantic/result_relevant"),
        _rc(position=3, expected="semantic/result_not_relevant"),
    ]
    res = join_labeled_rows(events, jev_rows, cases, "R")
    joined = [r for r in res.rows["result_relevant"] if r.ground_truth is not None]
    by_pos = {r.position: r.jev_probability for r in joined}
    assert by_pos == {1: 0.1, 2: 0.9, 3: 0.2}
    # Critically: NOT all collapsed to the last prediction (position 3 = 0.2).
    assert by_pos[2] == 0.9


# ===========================================================================
# 2. duplicate Jev position -> latest-by-timestamp + duplicate count
# ===========================================================================


def test_02_duplicate_position_latest_by_timestamp_reported():
    jev_rows = [
        _jev_row(position=2, prob=0.5, ts=1.0),
        _jev_row(position=2, prob=0.9, ts=5.0),  # later ts wins
    ]
    index, dupes = build_jev_prediction_index(jev_rows)
    assert dupes == 1
    key = ("R", "T", "result_relevant", 2)
    assert key in index
    assert index[key]["jev_probability"] == 0.9

    # Through the join: the human label joins the latest prediction.
    events = [{"run_id": "R", "trace_id": "T"}]
    cases = [_rc(position=2, expected="semantic/result_relevant")]
    res = join_labeled_rows(events, jev_rows, cases, "R")
    assert res.duplicate_prediction_keys == 1
    joined = [r for r in res.rows["result_relevant"] if r.ground_truth is not None]
    assert len(joined) == 1
    assert joined[0].jev_probability == 0.9


# ===========================================================================
# 3. missing browser CF -> ambiguous
# ===========================================================================


def test_03_missing_browser_cf_is_ambiguous():
    assert has_browser_counterfactual(_PRIMARY_COMPLETE_NO_CF) is False
    r = jev_needs_escalation_objective(dict(_PRIMARY_COMPLETE_NO_CF))
    assert r.label is None
    assert r.ambiguity_reason == "missing_browser_counterfactual"


# ===========================================================================
# 4. observed browser no-gain -> objective NO
# ===========================================================================


def test_04_observed_browser_no_gain_is_objective_no():
    facts = dict(_PRIMARY_COMPLETE_NO_CF)
    facts.update(
        browser_counterfactual_observed=True,
        browser_status="success",
        browser_extraction_success=True,
        browser_content_chars=1000,  # == primary: no material gain
        browser_gain_chars=0,
        browser_attempted=True,
        browser_success=True,
    )
    assert has_browser_counterfactual(facts) is True
    r = jev_needs_escalation_objective(facts)
    assert r.label == "semantic/no_more_content_needed"
    assert r.is_objective is True


# ===========================================================================
# 5. observed browser rescue -> objective YES
# ===========================================================================


def test_05_observed_browser_rescue_is_objective_yes():
    facts = {
        "status": "error",
        "primary_hard_signal": "JS_REQUIRED",
        "primary_extraction_success": False,
        "primary_content_chars": 0,
        "truncated": False,
        "continuation_available": False,
        "browser_counterfactual_observed": True,
        "browser_status": "success",
        "browser_extraction_success": True,
        "browser_content_chars": 5000,
        "browser_attempted": True,
        "browser_success": True,
    }
    r = jev_needs_escalation_objective(facts)
    assert r.label == "semantic/needs_more_content"
    assert r.is_objective is True


# ===========================================================================
# 6. browser CF artifact -> materializer joins by source_trace_id
# ===========================================================================


def test_06_materializer_joins_cf_by_source_trace_id(hermetic_stores, tmp_path):
    _, _, _ = hermetic_stores
    event = _fetch_event("run-cf", "t-cf", outcome=dict(_PRIMARY_COMPLETE_NO_CF))
    decision_store.record_event(event)

    cf_path = tmp_path / "browser-counterfactual.jsonl"
    cf_path.write_text(
        json.dumps(
            {
                "case_id": "cf:1",
                "run_id": "run-cf",
                "source_trace_id": "t-cf",
                "primary_status": "success",
                "browser_status": "success",
                "primary_chars": 1000,
                "browser_chars": 1000,
                "gain": 0,
                "primary_extraction_success": True,
                "browser_extraction_success": True,
            }
        )
        + "\n"
    )
    written = materialize_objective_replay_cases("run-cf", browser_counterfactual_path=str(cf_path))
    assert written == 1  # needs_escalation NO (would be ambiguous without the CF join)
    cases = decision_store.load_replay_cases(run_id="run-cf")
    ne = [c for c in cases if c["case_id"].endswith("needs_escalation")][0]
    assert ne["expected_label"] == "semantic/no_more_content_needed"
    assert ne["observed_outcome"]["browser_counterfactual_observed"] is True


# ===========================================================================
# 7 + 8. human gate strictly human_verified
# ===========================================================================


def _seed_gate_run(tmp_path: Path):
    for i in range(3):
        decision_store.record_event(_fetch_event("run-gate", f"f{i}", event_id=f"ev-g{i}"))
    # 2 human_verified result_usable + 1 objective_outcome result_usable.
    for i in range(2):
        decision_store.record_replay_case(
            ReplayCase(
                case_id=f"human:f{i}:result_usable",
                run_id="run-gate",
                trace_id=f"f{i}",
                domain="fetch",
                input_features={"question": "result_usable"},
                expected_label="semantic/result_usable",
                label_source="human_verified",
            )
        )
    decision_store.record_replay_case(
        ReplayCase(
            case_id="obj:ev-g0:result_usable",
            run_id="run-gate",
            trace_id="f0",
            domain="fetch",
            input_features={"question": "result_usable"},
            expected_label="semantic/result_not_usable",
            label_source="objective_outcome",
        )
    )


def test_07_human_gate_excludes_objective_labels(hermetic_stores):
    _, _, _ = hermetic_stores
    _seed_gate_run(Path("."))
    report = cli.build_run_report("run-gate")
    hg = report["human_gate"]
    assert hg["human_fetch_usable"] == 2  # objective label NOT counted
    assert hg["objective_fetch_usable"] == 1
    assert hg["objective_search_relevant"] == 0


def test_08_human_gate_counts_human_verified_only(hermetic_stores):
    _, _, _ = hermetic_stores
    _seed_gate_run(Path("."))
    report = cli.build_run_report("run-gate")
    hg = report["human_gate"]
    # Count is human_verified only; objective label did not inflate it.
    assert hg["human_fetch_usable"] == 2
    assert hg["objective_fetch_usable"] == 1
    # Threshold (20) is not met with only 2 labels, but the numerator is human-only.
    assert hg["passed_fetch_usable"] is False


# ===========================================================================
# 9 + 10. result rows vs Jev prediction count / real gate
# ===========================================================================


def test_09_search_result_rows_distinct_from_prediction_count(hermetic_stores):
    _, _, jdb = hermetic_stores
    # 5 search events, each result_count=10 -> 50 result rows...
    for i in range(5):
        decision_store.record_event(
            DecisionEvent(
                event_id=f"ev-s{i}",
                run_id="run-p",
                trace_id=f"s{i}",
                domain=DecisionDomain.SEARCH,
                stage=DecisionStage.FINAL,
                outcome_features={"status": "success", "result_count": 10},
            )
        )
    # ...but only 2 result_relevant Jev predictions.
    for i in range(2):
        _seed_jev_raw(
            jdb,
            {
                "run_id": "run-p",
                "trace_id": f"s{i}",
                "jev_question": "result_relevant",
                "position": 1,
                "jev_probability": 0.9,
            },
        )
    report = cli.build_run_report("run-p")
    assert report["counts"]["search_result_rows"] == 50
    assert report["counts"]["search_relevance_predictions"] == 2


def test_10_real_gate_uses_jev_prediction_count(hermetic_stores):
    _, _, jdb = hermetic_stores
    for i in range(5):
        decision_store.record_event(
            DecisionEvent(
                event_id=f"ev-s{i}",
                run_id="run-g",
                trace_id=f"s{i}",
                domain=DecisionDomain.SEARCH,
                stage=DecisionStage.FINAL,
                outcome_features={"status": "success", "result_count": 100},
            )
        )
    # Only 5 predictions despite 500 result rows.
    for i in range(5):
        _seed_jev_raw(
            jdb,
            {
                "run_id": "run-g",
                "trace_id": f"s{i}",
                "jev_question": "result_relevant",
                "position": 1,
                "jev_probability": 0.9,
            },
        )
    report = cli.build_run_report("run-g")
    assert report["counts"]["search_result_rows"] == 500  # observability only
    assert report["counts"]["search_relevance_predictions"] == 5
    rg = report["real_run_gate"]
    assert rg["passed_search_relevance_predictions"] is False  # gated on predictions
    assert "search_result_rows" not in rg["thresholds"]
    assert rg["thresholds"]["search_relevance_predictions"] == 100


# ===========================================================================
# 11. preflight JEV_ENABLED=false -> BLOCKED
# ===========================================================================


def test_11_preflight_jev_enabled_false_blocked(monkeypatch):
    from webscout_mcp import eval_preflight

    monkeypatch.setattr(eval_preflight, "_search_provider_count", lambda cfg: 2)
    monkeypatch.setattr(eval_preflight, "_crawl4ai_reachable", lambda url, timeout=1.5: False)
    monkeypatch.setattr(eval_preflight, "_typesafe_sdk_importable", lambda: True)
    monkeypatch.setattr(eval_preflight, "_credential_present", lambda cfg: True)
    monkeypatch.setenv("JEV_ENABLED", "false")
    report = eval_preflight.run_preflight()
    v = report["capabilities"]["jev_shadow"]
    assert v["status"] == "BLOCKED"
    assert any("JEV_ENABLED=false" in r for r in v["reasons"])


# ===========================================================================
# 12. report-only missing run DB -> non-zero
# ===========================================================================


def test_12_report_only_missing_run_db_nonzero(tmp_path, capsys):
    out_dir = tmp_path / "out"
    args = argparse.Namespace(out_dir=str(out_dir), run_id="nope", import_human_labels=None)
    rc = cli._handle_report_only(args)
    assert rc != 0
    err = capsys.readouterr().err
    assert "missing" in err.lower()


# ===========================================================================
# 13. human import wrong run_id rejected/skipped
# ===========================================================================


def test_13_human_import_wrong_run_id_skipped(hermetic_stores, tmp_path):
    _, _, _ = hermetic_stores
    rows = [
        {
            "case_id": "human:t:result_usable",
            "run_id": "runA",
            "trace_id": "t",
            "domain": "fetch",
            "question": "result_usable",
            "context": {},
            "expected_label": "semantic/result_usable",
        },
        {
            "case_id": "human:other:result_usable",
            "run_id": "runB",  # wrong run
            "trace_id": "other",
            "domain": "fetch",
            "question": "result_usable",
            "context": {},
            "expected_label": "semantic/result_usable",
        },
    ]
    p = tmp_path / "labels.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    n = eval_human.import_human_labels("runA", p)
    assert n == 1
    imported = decision_store.load_replay_cases(run_id="runA")
    assert len(imported) == 1
    assert decision_store.load_replay_cases(run_id="runB") == []


# ===========================================================================
# 14. result_relevant missing/invalid position rejected
# ===========================================================================


def test_14_result_relevant_missing_position_rejected(hermetic_stores, tmp_path):
    _, _, _ = hermetic_stores
    rows = [
        # valid: position 1
        {
            "case_id": "human:t:result_relevant:p1",
            "run_id": "runA",
            "trace_id": "t",
            "domain": "search",
            "question": "result_relevant",
            "context": {"position": 1},
            "expected_label": "semantic/result_relevant",
        },
        # invalid: no position
        {
            "case_id": "human:t:result_relevant:no",
            "run_id": "runA",
            "trace_id": "t",
            "domain": "search",
            "question": "result_relevant",
            "context": {},
            "expected_label": "semantic/result_relevant",
        },
        # invalid: position 0
        {
            "case_id": "human:t:result_relevant:p0",
            "run_id": "runA",
            "trace_id": "t",
            "domain": "search",
            "question": "result_relevant",
            "context": {"position": 0},
            "expected_label": "semantic/result_relevant",
        },
    ]
    p = tmp_path / "labels.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    n = eval_human.import_human_labels("runA", p)
    assert n == 1
    rc = decision_store.load_replay_cases(run_id="runA")[0]
    assert (rc["input_features"]["context"]["position"]) == 1


# ===========================================================================
# 15. operation coverage vs per-result prediction coverage reported separately
# ===========================================================================


def test_15_operation_and_per_result_coverage_reported_separately(hermetic_stores):
    _, _, jdb = hermetic_stores
    decision_store.record_event(
        DecisionEvent(
            event_id="ev-op",
            run_id="run-cov",
            trace_id="s0",
            domain=DecisionDomain.SEARCH,
            stage=DecisionStage.FINAL,
            outcome_features={"status": "success", "result_count": 5},
        )
    )
    _seed_jev_raw(
        jdb,
        {
            "run_id": "run-cov",
            "trace_id": "s0",
            "jev_question": "result_relevant",
            "position": 1,
            "jev_probability": 0.9,
        },
    )
    # Human label at position 1 joins; position 2 has no prediction.
    for pos in (1, 2):
        decision_store.record_replay_case(
            ReplayCase(
                case_id=f"human:s0:result_relevant:p{pos}",
                run_id="run-cov",
                trace_id="s0",
                domain="search",
                input_features={"question": "result_relevant", "context": {"position": pos}},
                expected_label="semantic/result_relevant",
                label_source="human_verified",
            )
        )
    report = cli.build_run_report("run-cov")
    hg = report["human_gate"]
    # Operation-level (run,trace) join coverage is separate from per-result counts.
    assert "operation_join_coverage" in hg
    assert hg["search_relevance_prediction_count"] == 1
    assert hg["human_relevance_joined_count"] == 1
    assert hg["human_relevance_missing_prediction"] == 1
