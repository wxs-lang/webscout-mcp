"""Tests for v1.5.0 Phase 2: Objective Decision Evaluation.

Covers:
  1  action label strict comparison
  2  outcome label strict comparison
  3  BROWSER_RESCUED failure regression (P0)
  4  FALLBACK_RESCUED failure regression (P0)
  5  objective continuation label
  6  browser rescue label
  7  browser material gain != rescue
  8  fallback rescue
  9  search fallback rescue
  10 all-empty
  11 all-failed
  12 ambiguous produces no fake label
  13 Jev cannot become label source
  14 needs_escalation metrics
  15 result_usable metrics
  16 result_relevant metrics
  17 Brier score
  18 calibration bins
  19 head-to-head matrix
  20 no-ground-truth exclusion
  21 join coverage gate
  22 human-only relevance rule
  23 privacy of reports (no body text / no secrets)
  24 reproducible run metadata
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from webscout_mcp.advisor_evaluator import (
    LabeledPrediction,
    brier_score,
    calibration_bins,
    check_join_gate,
    confusion_at_threshold,
    evaluate_question,
    head_to_head,
    semantic_label_to_ground_truth,
)
from webscout_mcp.decision_evaluator import evaluate_cases
from webscout_mcp.decision_event import LabelSource
from webscout_mcp.labels import (
    LabelTaxonomy,
    action_matches,
    outcome_holds,
    split_label,
)
from webscout_mcp.objective_labeler import (
    ObjectiveLabelResult,
    label_fetch_outcomes,
    label_search_outcomes,
)
from webscout_mcp.replay_case import ReplayCase


def _case(action="ACCEPT", expected="", outcome=None, source=LabelSource.OBJECTIVE_OUTCOME, domain="fetch"):
    return ReplayCase(
        domain=domain,
        production_decision={"action": action, "deterministic_reason": ""},
        observed_outcome=outcome or {},
        expected_label=expected,
        label_source=source,
    )


# ---------------------------------------------------------------------------
# 1. action label strict comparison
# ---------------------------------------------------------------------------


class TestActionLabelStrict:
    def test_action_namespace_exact_match(self):
        cases = [_case(action="BROWSER", expected="action/BROWSER")]
        assert evaluate_cases(cases).overall_agreement == 1

    def test_action_namespace_no_alias(self):
        # BROWSER_RESCUED must NOT alias to BROWSER action.
        cases = [_case(action="BROWSER", expected="action/BROWSER_RESCUED")]
        assert evaluate_cases(cases).overall_disagreement == 1

    def test_action_matches_helper(self):
        assert action_matches("browser", "BROWSER") is True
        assert action_matches("ACCEPT", "BROWSER") is False


# ---------------------------------------------------------------------------
# 2. outcome label strict comparison
# ---------------------------------------------------------------------------


class TestOutcomeLabelStrict:
    def test_outcome_does_not_use_action(self):
        # action=BROWSER but outcome facts say browser failed -> DISAGREE.
        cases = [
            _case(
                action="BROWSER",
                expected="outcome/browser_rescued",
                outcome={"browser_attempted": True, "browser_success": False, "primary_hard_signal": "JS_REQUIRED"},
            )
        ]
        r = evaluate_cases(cases)
        assert r.overall_disagreement == 1

    def test_split_label(self):
        assert split_label("action/BROWSER")[0] == "action"
        assert split_label("outcome/browser_rescued")[0] == "outcome"
        assert split_label("semantic/result_usable")[0] == "semantic"
        assert split_label("ACCEPT")[0] == "legacy_action"


# ---------------------------------------------------------------------------
# 3. BROWSER_RESCUED failure regression (P0 merge blocker)
# ---------------------------------------------------------------------------


class TestBrowserRescuedRegression:
    def test_browser_action_but_failed_is_disagree(self):
        cases = [
            _case(
                action="BROWSER",
                expected="outcome/browser_rescued",
                outcome={"browser_attempted": True, "browser_success": False},
            )
        ]
        r = evaluate_cases(cases)
        assert r.overall_agreement == 0
        assert r.overall_disagreement == 1

    def test_browser_success_with_primary_fail_is_agree(self):
        cases = [
            _case(
                action="BROWSER",
                expected="outcome/browser_rescued",
                outcome={
                    "browser_attempted": True,
                    "browser_success": True,
                    "primary_hard_signal": "JS_REQUIRED",
                },
            )
        ]
        assert evaluate_cases(cases).overall_agreement == 1


# ---------------------------------------------------------------------------
# 4. FALLBACK_RESCUED failure regression (P0 merge blocker)
# ---------------------------------------------------------------------------


class TestFallbackRescuedRegression:
    def test_fallback_used_but_final_failed_is_disagree(self):
        cases = [
            _case(
                action="PROVIDER_FALLBACK",
                expected="outcome/provider_fallback_rescued",
                outcome={
                    "fallback_attempted": True,
                    "fallback_success": False,
                    "primary_hard_signal": "TRANSPORT_FAILURE",
                    "status": "error",
                },
            )
        ]
        r = evaluate_cases(cases)
        assert r.overall_agreement == 0
        assert r.overall_disagreement == 1

    def test_fallback_rescued_success_is_agree(self):
        cases = [
            _case(
                action="PROVIDER_FALLBACK",
                expected="outcome/provider_fallback_rescued",
                outcome={
                    "fallback_attempted": True,
                    "fallback_success": True,
                    "primary_hard_signal": "TRANSPORT_FAILURE",
                    "status": "success",
                },
            )
        ]
        assert evaluate_cases(cases).overall_agreement == 1


# ---------------------------------------------------------------------------
# 5. objective continuation label
# ---------------------------------------------------------------------------


class TestContinuationLabel:
    def test_continuation_required(self):
        facts = {"truncated": True, "continuation_available": True}
        labels = label_fetch_outcomes(facts)
        assert any(l.label == "outcome/continuation_required" for l in labels)

    def test_continuation_not_required_when_not_truncated(self):
        facts = {"truncated": False, "continuation_available": True}
        assert not any(l.label == "outcome/continuation_required" for l in label_fetch_outcomes(facts))


# ---------------------------------------------------------------------------
# 6. browser rescue label
# ---------------------------------------------------------------------------


class TestBrowserRescueLabel:
    def test_rescue_requires_primary_fail_and_browser_ok(self):
        facts = {"browser_attempted": True, "browser_success": True, "primary_hard_signal": "JS_REQUIRED"}
        labels = label_fetch_outcomes(facts)
        assert any(l.label == "outcome/browser_rescued" for l in labels)

    def test_no_rescue_when_browser_failed(self):
        facts = {"browser_attempted": True, "browser_success": False, "primary_hard_signal": "JS_REQUIRED"}
        labels = label_fetch_outcomes(facts)
        assert not any(l.label == "outcome/browser_rescued" for l in labels)
        assert any(l.label == "outcome/browser_failed" for l in labels)


# ---------------------------------------------------------------------------
# 7. browser material gain != rescue
# ---------------------------------------------------------------------------


class TestMaterialGainNotRescue:
    def test_material_gain_requires_thresholds(self):
        facts = {
            "browser_success": True,
            "primary_content_chars": 1000,
            "browser_content_chars": 5000,
        }
        labels = label_fetch_outcomes(facts)
        assert any(l.label == "outcome/browser_material_gain" for l in labels)

    def test_small_gain_is_not_material(self):
        facts = {
            "browser_success": True,
            "primary_content_chars": 1000,
            "browser_content_chars": 1500,  # +500 < 2000
        }
        labels = label_fetch_outcomes(facts)
        assert not any(l.label == "outcome/browser_material_gain" for l in labels)


# ---------------------------------------------------------------------------
# 8. fallback rescue
# ---------------------------------------------------------------------------


class TestFallbackRescue:
    def test_fallback_rescued(self):
        facts = {"fallback_attempted": True, "fallback_success": True, "primary_hard_signal": "TRANSPORT_FAILURE"}
        assert any(l.label == "outcome/provider_fallback_rescued" for l in label_fetch_outcomes(facts))


# ---------------------------------------------------------------------------
# 9. search fallback rescue
# ---------------------------------------------------------------------------


class TestSearchFallbackRescue:
    def test_search_fallback_rescued(self):
        facts = {
            "result_count": 5,
            "fallback_count": 1,
            "attempt_summary": [
                {"ordinal": 1, "outcome": "empty", "reason": "EMPTY", "action": "TRY_NEXT_PROVIDER"},
                {"ordinal": 2, "outcome": "success", "reason": "OK", "action": "ACCEPT"},
            ],
        }
        labels = label_search_outcomes(facts)
        assert any(l.label == "outcome/search_fallback_rescued" for l in labels)

    def test_search_success(self):
        facts = {"result_count": 3, "fallback_count": 0}
        assert any(l.label == "outcome/search_success" for l in label_search_outcomes(facts))


# ---------------------------------------------------------------------------
# 10. all-empty
# ---------------------------------------------------------------------------


class TestAllEmpty:
    def test_all_empty(self):
        facts = {"status": "empty", "result_count": 0}
        assert outcome_holds("ALL_EMPTY", facts, domain="search")


# ---------------------------------------------------------------------------
# 11. all-failed
# ---------------------------------------------------------------------------


class TestAllFailed:
    def test_all_failed(self):
        facts = {"status": "error", "production_action": "RETURN_ERROR"}
        assert outcome_holds("ALL_FAILED", facts, domain="search")


# ---------------------------------------------------------------------------
# 12. ambiguous produces no fake label
# ---------------------------------------------------------------------------


class TestAmbiguousNoFakeLabel:
    def test_no_signal_is_ambiguous(self):
        facts = {}
        labels = label_fetch_outcomes(facts)
        assert all(l.is_objective is False and l.label is None for l in labels)

    def test_objective_label_result_ambiguous(self):
        r = ObjectiveLabelResult(label=None, confidence=0.0, evidence={}, is_objective=False, ambiguity_reason="x")
        assert r.label is None


# ---------------------------------------------------------------------------
# 13. Jev cannot become label source
# ---------------------------------------------------------------------------


class TestJevNotLabelSource:
    def test_replay_case_rejects_jev_verified(self):
        with pytest.raises(ValueError):
            ReplayCase(expected_label="x", label_source="jev_verified")

    def test_objective_labeler_does_not_read_jev(self):
        # Passing jev fields must not influence the objective label.
        facts = {"browser_attempted": True, "browser_success": False, "primary_hard_signal": "JS_REQUIRED"}
        facts_with_jev = dict(facts, jev_decision=True, jev_probability=0.99)
        a = [l.label for l in label_fetch_outcomes(facts)]
        b = [l.label for l in label_fetch_outcomes(facts_with_jev)]
        assert a == b


# ---------------------------------------------------------------------------
# 14-16. per-question metrics
# ---------------------------------------------------------------------------


def _row(question, gt, prob, rule=None):
    return LabeledPrediction(
        question=question,
        ground_truth=gt,
        label_source="human_verified",
        jev_decision=(prob >= 0.5) if prob is not None else None,
        jev_probability=prob,
        rule_decision=rule,
    )


class TestQuestionMetrics:
    def test_needs_escalation_metrics(self):
        rows = [
            _row("needs_escalation", True, 0.9, rule=True),
            _row("needs_escalation", True, 0.8, rule=False),
            _row("needs_escalation", False, 0.2, rule=False),
            _row("needs_escalation", False, 0.7, rule=False),  # FP
        ]
        m = evaluate_question("needs_escalation", rows)
        assert m.tp == 2 and m.tn == 1 and m.fp == 1 and m.fn == 0
        assert m.precision == round(2 / 3, 4)
        assert m.recall == 1.0

    def test_result_usable_metrics(self):
        rows = [_row("result_usable", True, 0.9), _row("result_usable", False, 0.1)]
        m = evaluate_question("result_usable", rows)
        assert m.tp == 1 and m.tn == 1

    def test_result_relevant_metrics(self):
        rows = [_row("result_relevant", True, 0.95), _row("result_relevant", True, 0.4)]
        m = evaluate_question("result_relevant", rows)
        assert m.tp == 1 and m.fn == 1


# ---------------------------------------------------------------------------
# 17. Brier score
# ---------------------------------------------------------------------------


class TestBrier:
    def test_brier_perfect(self):
        rows = [_row("q", True, 1.0), _row("q", False, 0.0)]
        assert brier_score(rows) == 0.0

    def test_brier_worst(self):
        rows = [_row("q", True, 0.0), _row("q", False, 1.0)]
        assert brier_score(rows) == 1.0


# ---------------------------------------------------------------------------
# 18. calibration bins
# ---------------------------------------------------------------------------


class TestCalibration:
    def test_five_bins(self):
        rows = [
            _row("q", True, 0.1),
            _row("q", True, 0.3),
            _row("q", False, 0.5),
            _row("q", True, 0.7),
            _row("q", False, 0.9),
        ]
        bins = calibration_bins(rows)
        assert len(bins) == 5
        assert sum(b["n"] for b in bins) == 5


# ---------------------------------------------------------------------------
# 19. head-to-head matrix
# ---------------------------------------------------------------------------


class TestHeadToHead:
    def test_matrix(self):
        rows = [
            _row("q", True, 0.9, rule=True),  # both correct
            _row("q", True, 0.2, rule=True),  # rule only correct (jev wrong)
            _row("q", False, 0.1, rule=True),  # jev only correct (rule wrong)
            _row("q", False, 0.9, rule=True),  # both wrong
        ]
        h = head_to_head(rows)
        assert h == {"both_correct": 1, "rule_only_correct": 1, "jev_only_correct": 1, "both_wrong": 1}


# ---------------------------------------------------------------------------
# 20. no-ground-truth exclusion
# ---------------------------------------------------------------------------


class TestNoGroundTruthExclusion:
    def test_ambiguous_excluded_from_confusion(self):
        rows = [
            _row("q", True, 0.9),
            LabeledPrediction(
                question="q",
                ground_truth=None,
                label_source="none",
                jev_decision=True,
                jev_probability=0.9,
                rule_decision=False,
            ),  # ambiguous
        ]
        c = confusion_at_threshold(rows)
        assert c["tp"] == 1 and sum(c.values()) == 1  # ambiguous not counted


# ---------------------------------------------------------------------------
# 21. join coverage gate
# ---------------------------------------------------------------------------


class TestJoinGate:
    def test_gate_passes(self):
        rep = {
            "advisor_enabled_decisions": 5,
            "joined_enabled_eligible": 5,
            "unexpected_unjoined": 0,
            "join_coverage": 1.0,
        }
        assert check_join_gate(rep).passed is True

    def test_gate_fails_on_unexpected(self):
        rep = {
            "advisor_enabled_decisions": 5,
            "joined_enabled_eligible": 4,
            "unexpected_unjoined": 1,
            "join_coverage": 0.8,
        }
        g = check_join_gate(rep)
        assert g.passed is False
        assert "unexpected_unjoined" in g.explanation

    def test_gate_fails_when_no_enabled(self):
        rep = {
            "advisor_enabled_decisions": 0,
            "joined_enabled_eligible": 0,
            "unexpected_unjoined": 0,
            "join_coverage": 0.0,
        }
        assert check_join_gate(rep).passed is False


# ---------------------------------------------------------------------------
# 22. human-only relevance rule
# ---------------------------------------------------------------------------


class TestHumanOnlyRelevance:
    def test_search_success_is_not_relevance_truth(self):
        # result_count>0 must not map to result_relevant=True.
        assert semantic_label_to_ground_truth("result_relevant", "outcome/search_success") is None

    def test_relevance_only_human_semantic(self):
        assert semantic_label_to_ground_truth("result_relevant", "semantic/result_relevant") is True
        assert semantic_label_to_ground_truth("result_relevant", "semantic/result_not_relevant") is False

    def test_result_usable_mapping(self):
        assert semantic_label_to_ground_truth("result_usable", "semantic/result_usable") is True
        assert semantic_label_to_ground_truth("result_usable", "semantic/result_not_usable") is False


# ---------------------------------------------------------------------------
# 23. privacy of reports
# ---------------------------------------------------------------------------


class TestReportPrivacy:
    def test_objective_evidence_has_no_body(self):
        facts = {
            "browser_attempted": True,
            "browser_success": True,
            "primary_hard_signal": "JS_REQUIRED",
            "some_body_text": "SECRET BODY THAT MUST NOT BE EVIDENCE",
        }
        for lr in label_fetch_outcomes(facts):
            if lr.is_objective:
                assert "some_body_text" not in lr.evidence
                assert "SECRET BODY" not in json.dumps(lr.evidence)

    def test_evidence_is_scalar_only(self):
        facts = {"browser_success": True, "primary_content_chars": 100, "nested": {"deep": "x"}}
        for lr in label_fetch_outcomes(facts):
            for v in lr.evidence.values():
                assert not isinstance(v, dict)


# ---------------------------------------------------------------------------
# 24. reproducible run metadata
# ---------------------------------------------------------------------------


class TestReproducibleMetadata:
    def test_taxonomy_is_stable(self):
        t = LabelTaxonomy().to_dict()
        assert "action" in t and "outcome" in t and "semantic" in t
        assert "action/browser" in t["action"]["fetch"]
        assert "outcome/browser_rescued" in t["outcome"]["fetch"]

    def test_corpus_files_present_and_parse(self):
        corpus = Path(__file__).resolve().parent.parent / "scripts" / "eval_corpus"
        fetch = json.loads((corpus / "fetch_urls.json").read_text())
        search = json.loads((corpus / "search_queries.json").read_text())
        assert len(fetch["urls"]) >= 60
        assert len(search["queries"]) >= 40


# ---------------------------------------------------------------------------
# semantic labels skipped by rule evaluator
# ---------------------------------------------------------------------------


class TestSemanticSkipped:
    def test_semantic_not_counted_in_rule_agreement(self):
        cases = [_case(action="ACCEPT", expected="semantic/result_usable")]
        r = evaluate_cases(cases)
        assert r.covered_cases == 0
        assert r.semantic_skipped == 1
