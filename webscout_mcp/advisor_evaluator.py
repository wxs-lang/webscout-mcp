"""Offline Jev (advisor) evaluation against trusted labels.

This module is READ-ONLY against production. It reads DecisionEvents, the Jev
shadow DB, and ReplayCases; it never routes, mutates, or thresholds production.

Core principles (Phase 2):
  * Metrics are computed SEPARATELY per Jev question (needs_escalation,
    result_usable, result_relevant). They are never blended into one accuracy.
  * Only cases with a trusted ground truth enter accuracy/Brier/calibration.
    ``label_source`` must be ``human_verified`` or ``objective_outcome``.
    ``jev_verified`` is rejected upstream by ReplayCase.
  * ``result_relevant`` ground truth is human-only; ``SEARCH_SUCCESS`` /
    result_count>0 is NOT relevance.
  * Disagreement without ground truth is counted separately, never as an error.
  * The join-coverage gate must pass (or be explained) before Jev accuracy is
    reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

JevQuestion = Literal["needs_escalation", "result_usable", "result_relevant"]

# Calibration bins (edges inclusive left, exclusive right).
CALIBRATION_BINS: tuple[tuple[float, float], ...] = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.0001),
)

MIN_N_FOR_CONCLUSION = 10  # below this, report only, do not conclude


@dataclass
class LabeledPrediction:
    """One (question, case) row joining trusted label + Jev prediction + rule."""

    question: str
    ground_truth: bool | None  # None = ambiguous/unlabeled -> excluded
    label_source: str
    jev_decision: bool | None
    jev_probability: float | None
    rule_decision: bool | None
    trace_id: str = ""
    run_id: str = ""


@dataclass
class QuestionMetrics:
    question: str
    n_total: int = 0
    n_labeled: int = 0
    n_excluded_ambiguous: int = 0
    n_no_ground_truth_disagreement: int = 0
    coverage: float = 0.0
    threshold: float = 0.5
    tp: int = 0
    tn: int = 0
    fp: int = 0
    fn: int = 0
    precision: float | None = None
    recall: float | None = None
    specificity: float | None = None
    accuracy: float | None = None
    brier: float | None = None
    calibration: list[dict[str, Any]] = field(default_factory=list)
    head_to_head: dict[str, int] = field(default_factory=dict)
    conclusion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "n_total": self.n_total,
            "n_labeled": self.n_labeled,
            "n_excluded_ambiguous": self.n_excluded_ambiguous,
            "n_no_ground_truth_disagreement": self.n_no_ground_truth_disagreement,
            "coverage": round(self.coverage, 4),
            "threshold": self.threshold,
            "confusion": {
                "tp": self.tp,
                "tn": self.tn,
                "fp": self.fp,
                "fn": self.fn,
            },
            "precision": self.precision,
            "recall": self.recall,
            "specificity": self.specificity,
            "accuracy": self.accuracy,
            "brier": self.brier,
            "calibration": self.calibration,
            "head_to_head": self.head_to_head,
            "conclusion": self.conclusion,
        }


def _safe_div(a: float, b: float) -> float | None:
    if not b:
        return None
    return round(a / b, 4)


def confusion_at_threshold(rows: list[LabeledPrediction], threshold: float = 0.5) -> dict[str, int]:
    tp = tn = fp = fn = 0
    for r in rows:
        if r.ground_truth is None or r.jev_probability is None:
            continue
        pred_yes = r.jev_probability >= threshold
        actual_yes = bool(r.ground_truth)
        if pred_yes and actual_yes:
            tp += 1
        elif pred_yes and not actual_yes:
            fp += 1
        elif not pred_yes and actual_yes:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def brier_score(rows: list[LabeledPrediction]) -> float | None:
    diffs = [
        (float(r.jev_probability) - (1.0 if r.ground_truth else 0.0)) ** 2
        for r in rows
        if r.ground_truth is not None and r.jev_probability is not None
    ]
    if not diffs:
        return None
    return round(sum(diffs) / len(diffs), 5)


def calibration_bins(rows: list[LabeledPrediction]) -> list[dict[str, Any]]:
    labeled = [r for r in rows if r.ground_truth is not None and r.jev_probability is not None]
    out: list[dict[str, Any]] = []
    for lo, hi in CALIBRATION_BINS:
        bucket = [r for r in labeled if lo <= float(r.jev_probability) < hi]
        n = len(bucket)
        avg_p = round(sum(float(r.jev_probability) for r in bucket) / n, 4) if n else None
        obs_pos = round(sum(1 for r in bucket if r.ground_truth) / n, 4) if n else None
        out.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": n,
                "avg_probability": avg_p,
                "observed_positive_rate": obs_pos,
            }
        )
    return out


def head_to_head(rows: list[LabeledPrediction]) -> dict[str, int]:
    """Deterministic rule vs Jev on cases that have BOTH + trusted label."""
    both_correct = rule_only = jev_only = both_wrong = 0
    for r in rows:
        if r.ground_truth is None or r.jev_probability is None or r.rule_decision is None:
            continue
        jev_yes = r.jev_probability >= 0.5
        gt_yes = bool(r.ground_truth)
        rule_correct = bool(r.rule_decision) == gt_yes
        jev_correct = jev_yes == gt_yes
        if rule_correct and jev_correct:
            both_correct += 1
        elif rule_correct and not jev_correct:
            rule_only += 1
        elif jev_correct and not rule_correct:
            jev_only += 1
        else:
            both_wrong += 1
    return {
        "both_correct": both_correct,
        "rule_only_correct": rule_only,
        "jev_only_correct": jev_only,
        "both_wrong": both_wrong,
    }


def evaluate_question(question: str, rows: list[LabeledPrediction]) -> QuestionMetrics:
    """Evaluate one Jev question. Rows may include ambiguous/unlabeled cases."""
    m = QuestionMetrics(question=question, n_total=len(rows))
    labeled = [r for r in rows if r.ground_truth is not None]
    m.n_labeled = len(labeled)
    m.n_excluded_ambiguous = len(rows) - len(labeled)
    m.coverage = _safe_div(len(labeled), len(rows)) or 0.0

    # Disagreement without ground truth: rule and jev differ but no label.
    for r in rows:
        if r.ground_truth is None and r.rule_decision is not None and r.jev_probability is not None:
            if bool(r.rule_decision) != (r.jev_probability >= 0.5):
                m.n_no_ground_truth_disagreement += 1

    c = confusion_at_threshold(labeled, m.threshold)
    m.tp, m.tn, m.fp, m.fn = c["tp"], c["tn"], c["fp"], c["fn"]
    predicted_pos = m.tp + m.fp
    actual_pos = m.tp + m.fn
    actual_neg = m.tn + m.fp
    m.precision = _safe_div(m.tp, predicted_pos)
    m.recall = _safe_div(m.tp, actual_pos)
    m.specificity = _safe_div(m.tn, actual_neg)
    m.accuracy = _safe_div(m.tp + m.tn, m.tp + m.tn + m.fp + m.fn)
    m.brier = brier_score(labeled)
    m.calibration = calibration_bins(labeled)
    m.head_to_head = head_to_head(labeled)

    if m.n_labeled < MIN_N_FOR_CONCLUSION:
        m.conclusion = (
            f"n_labeled={m.n_labeled} < {MIN_N_FOR_CONCLUSION}: report only, evidence insufficient to conclude"
        )
    return m


# ---------------------------------------------------------------------------
# Join coverage gate.
# ---------------------------------------------------------------------------


@dataclass
class JoinGateResult:
    passed: bool
    advisor_enabled_decisions: int
    joined_enabled_eligible: int
    unexpected_unjoined: int
    join_coverage: float
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "advisor_enabled_decisions": self.advisor_enabled_decisions,
            "joined_enabled_eligible": self.joined_enabled_eligible,
            "unexpected_unjoined": self.unexpected_unjoined,
            "join_coverage": round(self.join_coverage, 4),
            "explanation": self.explanation,
        }


def check_join_gate(join_report: dict[str, Any], coverage_target: float = 1.0) -> JoinGateResult:
    """Correlation gate before trusting Jev accuracy.

    Requires advisor_enabled_decisions > 0, unexpected_unjoined == 0, and
    join_coverage >= target. If it fails, Jev accuracy must not be interpreted.
    """
    enabled = int(join_report.get("advisor_enabled_decisions", 0) or 0)
    joined = int(join_report.get("joined_enabled_eligible", 0) or 0)
    unexpected = int(join_report.get("unexpected_unjoined", 0) or 0)
    coverage = float(join_report.get("join_coverage", 0.0) or 0.0)

    reasons: list[str] = []
    if enabled <= 0:
        reasons.append("advisor_enabled_decisions==0 (no Jev-enabled decisions in run)")
    if unexpected != 0:
        reasons.append(f"unexpected_unjoined={unexpected} (correlation failure)")
    if enabled > 0 and coverage < coverage_target:
        reasons.append(f"join_coverage={coverage:.3f} < target {coverage_target:.2f}")

    passed = len(reasons) == 0
    explanation = "OK" if passed else "JEV_CORRELATION_NOT_TRUSTED: " + "; ".join(reasons)
    return JoinGateResult(
        passed=passed,
        advisor_enabled_decisions=enabled,
        joined_enabled_eligible=joined,
        unexpected_unjoined=unexpected,
        join_coverage=coverage,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Mapping from semantic labels to boolean ground truth per question.
# ---------------------------------------------------------------------------

_SEMANTIC_POSITIVE: dict[str, set[str]] = {
    "needs_escalation": {"SEMANTIC/NEEDS_MORE_CONTENT"},
    "result_usable": {"SEMANTIC/RESULT_USABLE"},
    "result_relevant": {"SEMANTIC/RESULT_RELEVANT"},
}


def semantic_label_to_ground_truth(question: str, expected_label: str) -> bool | None:
    """Map a ReplayCase expected_label to a boolean ground truth, or None.

    Only semantic/* labels map. outcome/* labels are not Jev-question answers.
    result_relevant requires label_source=human_verified (enforced by caller).
    """
    if not expected_label:
        return None
    canon = expected_label.strip().upper().replace("-", "_").replace(" ", "_")
    pos = _SEMANTIC_POSITIVE.get(question, set())
    neg_map = {
        "needs_escalation": "SEMANTIC/NO_MORE_CONTENT_NEEDED",
        "result_usable": "SEMANTIC/RESULT_NOT_USABLE",
        "result_relevant": "SEMANTIC/RESULT_NOT_RELEVANT",
    }
    if canon in pos:
        return True
    if canon == neg_map.get(question):
        return False
    return None
