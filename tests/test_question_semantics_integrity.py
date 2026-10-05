"""v1.5.0 Phase 2.1.2 PART B — Question Semantics Integrity tests.

Deterministic, hermetic, offline. Locks the browser-escalation-only semantics of
the ``needs_escalation`` Jev question: its ground truth must mean BROWSER
escalation specifically, not generic "any recovery needed".

Scenarios covered (mirrors the acceptance list):

 8  continuation required WITHOUT browser evidence -> AMBIGUOUS (not a YES)
 9  provider-fallback rescued WITHOUT browser evidence -> AMBIGUOUS (not a YES)
10  production browser rescue -> browser_escalation_warranted (YES)
11  browser counterfactual rescue -> browser_escalation_warranted (YES)
12  observed browser CF, no gain, primary structurally complete -> NOT_WARRANTED
13  new browser-escalation labels map to boolean ground truth (agent A mapping)
14  legacy needs_more_content / no_more_content_needed still map (back-compat)
16  import_human_labels rejects wrong/typo/legacy (question, label) pairs
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webscout_mcp import decision_store, eval_human, jev_store
from webscout_mcp.advisor_evaluator import semantic_label_to_ground_truth
from webscout_mcp.labels import allowed_human_labels
from webscout_mcp.objective_labeler import jev_needs_escalation_objective

# ---------------------------------------------------------------------------
# Fixtures
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


# A structurally complete primary: extraction ok, transport ok, no hard signal,
# not truncated, no continuation.
_COMPLETE_PRIMARY = {
    "status": "success",
    "http_status_code": 200,
    "primary_extraction_success": True,
    "primary_content_chars": 5000,
    "truncated": False,
    "continuation_available": False,
}


# ===========================================================================
# 8. continuation required WITHOUT browser evidence -> AMBIGUOUS
# ===========================================================================


def test_08_continuation_without_browser_evidence_is_ambiguous():
    facts = {"truncated": True, "continuation_available": True}
    r = jev_needs_escalation_objective(facts)
    # Proves a continuation was needed, NOT that a browser was warranted.
    assert r.label is None
    assert r.is_objective is False
    assert r.ambiguity_reason == "missing_browser_evidence"
    assert r.label != "semantic/browser_escalation_warranted"


# ===========================================================================
# 9. provider-fallback rescued WITHOUT browser evidence -> AMBIGUOUS
# ===========================================================================


def test_09_provider_fallback_rescued_without_browser_evidence_is_ambiguous():
    facts = {
        "primary_hard_signal": "TRANSPORT_FAILURE",
        "primary_extraction_success": False,
        "primary_content_chars": 0,
        "fallback_attempted": True,
        "fallback_success": True,
    }
    r = jev_needs_escalation_objective(facts)
    # Proved a provider fallback rescued it, NOT that a browser was warranted.
    assert r.label is None
    assert r.is_objective is False
    assert r.ambiguity_reason == "missing_browser_evidence"


# ===========================================================================
# 10. production browser rescue -> browser_escalation_warranted
# ===========================================================================


def test_10_production_browser_rescue_is_warranted():
    facts = {
        "primary_hard_signal": "JS_REQUIRED",
        "primary_extraction_success": False,
        "primary_content_chars": 0,
        "browser_attempted": True,
        "browser_success": True,
    }
    r = jev_needs_escalation_objective(facts)
    assert r.label == "semantic/browser_escalation_warranted"
    assert r.is_objective is True
    assert r.confidence == pytest.approx(0.85)


# ===========================================================================
# 11. browser counterfactual rescue -> browser_escalation_warranted
# ===========================================================================


def test_11_browser_counterfactual_rescue_is_warranted():
    facts = {
        "primary_hard_signal": "JS_REQUIRED",
        "primary_extraction_success": False,
        "primary_content_chars": 0,
        "browser_counterfactual_observed": True,
        "browser_status": "success",
        "browser_extraction_success": True,
        "browser_content_chars": 5000,
    }
    r = jev_needs_escalation_objective(facts)
    assert r.label == "semantic/browser_escalation_warranted"
    assert r.is_objective is True


# ===========================================================================
# 12. observed browser CF, no gain, primary complete -> NOT_WARRANTED
# ===========================================================================


def test_12_observed_browser_no_gain_complete_primary_is_not_warranted():
    facts = dict(_COMPLETE_PRIMARY)
    facts.update(
        browser_counterfactual_observed=True,
        browser_status="success",
        browser_extraction_success=True,
        browser_content_chars=5000,  # == primary: no material gain
        browser_gain_chars=0,
    )
    r = jev_needs_escalation_objective(facts)
    assert r.label == "semantic/browser_escalation_not_warranted"
    assert r.is_objective is True
    assert r.confidence == pytest.approx(0.70)


# ===========================================================================
# 13. new browser-escalation labels -> boolean ground truth (agent A mapping)
# ===========================================================================


def test_13_new_browser_escalation_labels_map_to_ground_truth():
    assert semantic_label_to_ground_truth("needs_escalation", "semantic/browser_escalation_warranted") is True
    assert semantic_label_to_ground_truth("needs_escalation", "semantic/browser_escalation_not_warranted") is False


# ===========================================================================
# 14. legacy labels still map (backward-compatible aliases)
# ===========================================================================


def test_14_legacy_labels_still_map_to_ground_truth():
    assert semantic_label_to_ground_truth("needs_escalation", "semantic/needs_more_content") is True
    assert semantic_label_to_ground_truth("needs_escalation", "semantic/no_more_content_needed") is False


# ===========================================================================
# allowed_human_labels vocabulary (B1)
# ===========================================================================


def test_allowed_human_labels_vocabulary():
    assert allowed_human_labels("needs_escalation") == frozenset(
        {
            "semantic/browser_escalation_warranted",
            "semantic/browser_escalation_not_warranted",
        }
    )
    assert allowed_human_labels("result_usable") == frozenset({"semantic/result_usable", "semantic/result_not_usable"})
    assert allowed_human_labels("result_relevant") == frozenset(
        {"semantic/result_relevant", "semantic/result_not_relevant"}
    )
    # Unknown question -> empty (rejects everything).
    assert allowed_human_labels("not_a_question") == frozenset()
    assert allowed_human_labels("") == frozenset()


# ===========================================================================
# 16. import_human_labels validates (question, label) pairs
# ===========================================================================


def test_16_import_human_labels_rejects_invalid_pairs(hermetic_stores, tmp_path):
    _, _, _ = hermetic_stores
    rows = [
        # (a) result_usable carrying a result_relevant label -> invalid.
        {
            "case_id": "human:a:result_usable",
            "run_id": "runV",
            "trace_id": "a",
            "domain": "fetch",
            "question": "result_usable",
            "context": {},
            "expected_label": "semantic/result_relevant",
        },
        # (b) result_relevant at valid position 1, but typo label -> invalid.
        {
            "case_id": "human:b:result_relevant:p1",
            "run_id": "runV",
            "trace_id": "b",
            "domain": "search",
            "question": "result_relevant",
            "context": {"position": 1},
            "expected_label": "semantic/result_usabel",
        },
        # (c) needs_escalation carrying the legacy generic label -> invalid.
        {
            "case_id": "human:c:needs_escalation",
            "run_id": "runV",
            "trace_id": "c",
            "domain": "fetch",
            "question": "needs_escalation",
            "context": {},
            "expected_label": "semantic/needs_more_content",
        },
        # Valid: result_usable.
        {
            "case_id": "human:d:result_usable",
            "run_id": "runV",
            "trace_id": "d",
            "domain": "fetch",
            "question": "result_usable",
            "context": {},
            "expected_label": "semantic/result_usable",
        },
        # Valid: result_relevant at position 1.
        {
            "case_id": "human:e:result_relevant:p1",
            "run_id": "runV",
            "trace_id": "e",
            "domain": "search",
            "question": "result_relevant",
            "context": {"position": 1},
            "expected_label": "semantic/result_relevant",
        },
        # Valid: needs_escalation browser-escalation warranted.
        {
            "case_id": "human:f:needs_escalation",
            "run_id": "runV",
            "trace_id": "f",
            "domain": "fetch",
            "question": "needs_escalation",
            "context": {},
            "expected_label": "semantic/browser_escalation_warranted",
        },
    ]
    p = tmp_path / "labels.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    n = eval_human.import_human_labels("runV", p)
    assert n == 3

    imported = decision_store.load_replay_cases(run_id="runV")
    imported_labels = sorted(c["expected_label"] for c in imported)
    assert imported_labels == sorted(
        [
            "semantic/result_usable",
            "semantic/result_relevant",
            "semantic/browser_escalation_warranted",
        ]
    )
    # The three invalid rows must NOT have been imported.
    assert all(c["trace_id"] not in ("a", "b", "c") for c in imported)
