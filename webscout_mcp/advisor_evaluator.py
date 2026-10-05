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
    # Search result_relevant correlation position (1-based). None for Fetch
    # questions (needs_escalation / result_usable), which have no position.
    position: int | None = None


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


# ---------------------------------------------------------------------------
# Phase 2.1: run-scoped labeled-row join (evaluation-only).
# ---------------------------------------------------------------------------

EVALUATION_QUESTIONS: tuple[str, ...] = ("needs_escalation", "result_usable", "result_relevant")

# Only trusted sources may mint ground truth. jev_verified is rejected upstream.
_TRUSTED_LABEL_SOURCES = {"human_verified", "objective_outcome"}


def _jev_resolved_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Correlation key for a raw Jev shadow row.

    Fetch questions (``needs_escalation`` / ``result_usable``) have NO search
    result position, so they stay on the 3-tuple
    ``(run_id, trace_id, question)``.

    Search ``result_relevant`` predictions are per search *result position*
    (position 1/2/3 ... of one query trace). Keying on the 3-tuple would make
    every position collapse onto the last prediction for that trace, so we use
    the 4-tuple ``(run_id, trace_id, question, position)``.
    """
    run_id = row.get("run_id") or ""
    trace_id = row.get("trace_id") or ""
    question = row.get("jev_question") or ""
    base: tuple[Any, ...] = (run_id, trace_id, question)
    if question == "result_relevant":
        return base + (row.get("position"),)
    return base


def _rc_position(rc: Any) -> Any:
    """Read the human Search result position from a ReplayCase.

    ``import_human_labels`` stores the reviewer's per-row context at
    ``input_features["context"]`` including ``position``. Fetch cases carry no
    position. Returns ``None`` when absent/invalid.
    """
    context = (getattr(rc, "input_features", None) or {}).get("context") or {}
    pos = context.get("position")
    if isinstance(pos, bool):  # bool is an int subclass; reject it as a position
        return None
    if isinstance(pos, int):
        return pos
    return None


def build_jev_prediction_index(
    jev_rows: list[dict[str, Any]],
) -> tuple[dict[tuple[Any, ...], dict[str, Any]], int]:
    """Build the resolved-key Jev prediction index.

    Duplicate rows sharing a resolved key are NOT silently last-wins: the record
    with the greatest ``timestamp`` is selected deterministically, breaking ties
    by input row order (a later row wins an exact timestamp tie). The number of
    duplicated keys (i.e. rows dropped as duplicates) is returned so it is
    reported, not hidden.

    Returns ``(index, duplicate_prediction_keys)``.
    """
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    best_order: dict[tuple[Any, ...], int] = {}
    duplicate_prediction_keys = 0

    def _sortable(ts: Any, order: int) -> tuple[float, int]:
        if isinstance(ts, (int, float)) and not isinstance(ts, bool):
            return (float(ts), order)
        return (float("-inf"), order)

    for order, row in enumerate(jev_rows):
        key = _jev_resolved_key(row)
        candidate = (_sortable(row.get("timestamp"), order), row)
        if key not in best:
            best[key] = row
            best_order[key] = order
            continue
        duplicate_prediction_keys += 1
        cur_sort = _sortable(best[key].get("timestamp"), best_order[key])
        if candidate[0] >= cur_sort:
            best[key] = row
            best_order[key] = order
    return best, duplicate_prediction_keys


@dataclass
class JoinResult:
    """Result of joining trusted ReplayCases with Jev shadow predictions."""

    rows: dict[str, list[LabeledPrediction]]
    duplicate_prediction_keys: int


def join_labeled_rows(
    events: list[dict[str, Any]],
    jev_rows: list[dict[str, Any]],
    replay_cases: list[Any],
    run_id: str,
) -> JoinResult:
    """Pure join of trusted ReplayCases + Jev rows for ONE run.

    The correlation key is strictly:
      * Fetch questions: ``(run_id, trace_id, question)``
      * Search ``result_relevant``: ``(run_id, trace_id, question, position)``

    ``case_id`` is NEVER used as a trace. Duplicate Jev prediction keys are
    resolved latest-by-timestamp (see :func:`build_jev_prediction_index`) and the
    dropped-duplicate count is surfaced on ``JoinResult.duplicate_prediction_keys``.

    * For each trusted ReplayCase (``label_source`` human_verified /
      objective_outcome), derive a boolean ground truth per question via
      :func:`semantic_label_to_ground_truth`. When non-None AND a Jev row
      exists for the resolved key, emit a ``LabeledPrediction`` whose
      ``trace_id`` is the ReplayCase's TRACE_ID (never its case_id), whose
      ``run_id`` is the case's run_id, and (for result_relevant) whose
      ``position`` is the human Search result position.
    * Every Jev row not consumed as a trusted label is appended with
      ``ground_truth=None``. A Jev prediction can NEVER become a label.

    Args:
        events: DecisionEvents loaded for this run (used to validate that a
            labeled trace corresponds to a real production decision).
        jev_rows: raw Jev shadow rows for this run.
        replay_cases: trusted ReplayCases for this run.
        run_id: the scoped run id.
    """
    result: dict[str, list[LabeledPrediction]] = {q: [] for q in EVALUATION_QUESTIONS}

    event_traces = {(e.get("run_id") or "", e.get("trace_id") or "") for e in events}

    jev_index, duplicate_prediction_keys = build_jev_prediction_index(jev_rows)

    used_jev_keys: set[tuple[Any, ...]] = set()

    for rc in replay_cases:
        label_source_value = getattr(rc.label_source, "value", rc.label_source)
        if label_source_value not in _TRUSTED_LABEL_SOURCES:
            continue
        rc_run = rc.run_id or run_id
        rc_trace = rc.trace_id or ""
        if (rc_run, rc_trace) not in event_traces:
            continue  # a label without a real production trace in this run: skip
        for question in EVALUATION_QUESTIONS:
            ground_truth = semantic_label_to_ground_truth(question, rc.expected_label or "")
            if ground_truth is None:
                continue
            key: tuple[Any, ...] = (rc_run, rc_trace, question)
            position: int | None = None
            if question == "result_relevant":
                position = _rc_position(rc)
                key = key + (position,)
            jrow = jev_index.get(key)
            if jrow is None:
                continue  # ground truth cannot join without its Jev prediction
            used_jev_keys.add(key)
            result[question].append(
                LabeledPrediction(
                    question=question,
                    ground_truth=ground_truth,
                    label_source=label_source_value,
                    jev_decision=jrow.get("jev_decision"),
                    jev_probability=jrow.get("jev_probability"),
                    rule_decision=jrow.get("rule_decision"),
                    trace_id=rc_trace,
                    run_id=rc_run,
                    position=position,
                )
            )

    # Ambiguous/unlabeled Jev predictions: appended, never relabeled.
    for key, jrow in jev_index.items():
        if key in used_jev_keys:
            continue
        bucket = result.get(key[2])
        if bucket is None:
            continue
        bucket.append(
            LabeledPrediction(
                question=key[2],
                ground_truth=None,
                label_source="",
                jev_decision=jrow.get("jev_decision"),
                jev_probability=jrow.get("jev_probability"),
                rule_decision=jrow.get("rule_decision"),
                trace_id=key[1],
                run_id=key[0],
                position=(key[3] if len(key) == 4 else None),
            )
        )

    return JoinResult(rows=result, duplicate_prediction_keys=duplicate_prediction_keys)


def build_labeled_rows(run_id: str) -> dict[str, list[LabeledPrediction]]:
    """Materialize run-scoped labeled rows for the OFFLINE EVALUATION CLI.

    Read-only against production. Lazily imports ``decision_store`` /
    ``jev_store`` / ``ReplayCase`` to avoid import cycles. Reads:
      * DecisionEvents for the run via ``decision_store``,
      * Jev shadow rows for the run via the configured jev_store DB,
      * ReplayCases for the run via ``decision_store.load_replay_cases(run_id=...)``.

    Returns a mapping ``question -> [LabeledPrediction]`` joined on the resolved
    correlation key (3-tuple for Fetch, 4-tuple incl. position for Search
    ``result_relevant``). See :func:`join_labeled_rows`.

    Duplicate Jev prediction keys are resolved latest-by-timestamp internally;
    the dropped-duplicate count is surfaced by the report via
    :func:`build_jev_prediction_index`.
    """
    import sqlite3

    from . import decision_store, jev_store
    from .logging_config import get_logger
    from .replay_case import ReplayCase

    events = decision_store.load_events_for_run(run_id)

    jev_rows: list[dict[str, Any]] = []
    try:
        jev_db = jev_store.db_path()
        if jev_db.exists():
            with sqlite3.connect(str(jev_db), timeout=5.0) as jc:
                jc.row_factory = sqlite3.Row
                rows = jc.execute("SELECT * FROM jev_records WHERE run_id = ?", (run_id,)).fetchall()
            for row in rows:
                d = dict(row)
                for k in ("jev_decision", "rule_decision", "browser_attempted", "browser_success"):
                    if d.get(k) is not None:
                        d[k] = bool(d[k])
                jev_rows.append(d)
    except Exception:
        get_logger(__name__).warning("build_labeled_rows: jev store read failed", exc_info=True)

    replay_cases = [ReplayCase.from_dict(d) for d in decision_store.load_replay_cases(run_id=run_id)]

    return join_labeled_rows(events, jev_rows, replay_cases, run_id).rows
