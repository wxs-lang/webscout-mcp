"""Offline evaluator for ReplayCases.

Compares the production deterministic decision against the trusted
``expected_label`` on each ReplayCase. Outputs per-label and aggregate
metrics: coverage, agreement, false_positive, false_negative.

This is intentionally NOT a single Accuracy score. Different label types
have different semantics (e.g. "browser_rescued" vs "should_stop"), so
they are reported separately. Jev predictions are never used as labels;
they may be joined for comparison but do not affect these metrics.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .labels import action_matches, outcome_holds, split_label
from .replay_case import ReplayCase


@dataclass
class LabelMetrics:
    """Metrics for one expected_label value."""

    label: str
    total: int = 0
    agreed: int = 0
    disagreed: int = 0
    false_positive: int = 0  # production said this label, expected did not
    false_negative: int = 0  # expected this label, production did not

    @property
    def agreement_rate(self) -> float:
        return self.agreed / self.total if self.total else 0.0


@dataclass
class EvaluationResult:
    """Aggregate evaluation result."""

    total_cases: int = 0
    covered_cases: int = 0
    uncovered_cases: int = 0
    overall_agreement: int = 0
    overall_disagreement: int = 0
    # Semantic-* labels are Jev-question ground truth; they are NOT comparable
    # by rule-action agreement and are evaluated by advisor_evaluator instead.
    semantic_skipped: int = 0
    per_label: dict[str, LabelMetrics] = field(default_factory=dict)
    per_domain: dict[str, dict[str, int]] = field(default_factory=dict)
    disagreements: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "covered_cases": self.covered_cases,
            "uncovered_cases": self.uncovered_cases,
            "semantic_skipped": self.semantic_skipped,
            "coverage_rate": self.covered_cases / self.total_cases if self.total_cases else 0.0,
            "overall_agreement": self.overall_agreement,
            "overall_disagreement": self.overall_disagreement,
            "overall_agreement_rate": (self.overall_agreement / self.covered_cases if self.covered_cases else 0.0),
            "per_label": {
                label: {
                    "total": m.total,
                    "agreed": m.agreed,
                    "disagreed": m.disagreed,
                    "false_positive": m.false_positive,
                    "false_negative": m.false_negative,
                    "agreement_rate": round(m.agreement_rate, 4),
                }
                for label, m in sorted(self.per_label.items())
            },
            "per_domain": self.per_domain,
            "disagreement_count": len(self.disagreements),
            "disagreements_sample": self.disagreements[:20],
        }


def _production_action(case: ReplayCase) -> str:
    """Extract the production action from a ReplayCase."""
    pd = case.production_decision or {}
    return str(pd.get("action") or pd.get("deterministic_action") or "")


def evaluate_cases(cases: Iterable[ReplayCase | dict[str, Any]]) -> EvaluationResult:
    """Evaluate a list of ReplayCases against their expected labels.

    A case is "covered" if it has a non-empty expected_label AND a non-empty
    production action. Agreement means the production action matches the
    expected label (or the expected label maps to that action).

    Label semantics:
      - Labels like "ACCEPT", "BROWSER", "CONTINUE_CONTENT", "STOP",
        "TRY_NEXT_PROVIDER", "RETURN_EMPTY", "RETURN_ERROR" are compared
        directly against production_action.
      - Labels like "browser_rescued", "fallback_rescued", "all_empty",
        "all_failed" are outcome labels; they are checked against
        observed_outcome fields.
    """
    result = EvaluationResult()
    label_metrics: dict[str, LabelMetrics] = defaultdict(lambda: LabelMetrics(label=""))
    domain_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "agreed": 0})

    for case in cases:
        if isinstance(case, dict):
            case = ReplayCase.from_dict(case)

        result.total_cases += 1
        domain = case.domain or "unknown"
        domain_counts[domain]["total"] += 1

        expected = (case.expected_label or "").strip()
        prod_action = _production_action(case)

        if not expected or not prod_action:
            result.uncovered_cases += 1
            continue

        # Semantic labels are Jev-question ground truth, not rule-action
        # agreement. They belong to advisor_evaluator and must NOT be mixed
        # into rule accuracy here.
        ns, canon = split_label(expected)
        if ns == "semantic":
            result.semantic_skipped += 1
            continue

        result.covered_cases += 1

        # Determine agreement.
        agreed = _check_agreement(case, expected, prod_action)

        if agreed:
            result.overall_agreement += 1
            domain_counts[domain]["agreed"] += 1
        else:
            result.overall_disagreement += 1
            result.disagreements.append(
                {
                    "case_id": case.case_id,
                    "domain": domain,
                    "expected_label": expected,
                    "production_action": prod_action,
                    "label_source": case.label_source.value
                    if hasattr(case.label_source, "value")
                    else case.label_source,
                    "notes": case.notes,
                }
            )

        # Per-label metrics.
        lm = label_metrics[expected]
        lm.label = expected
        lm.total += 1
        if agreed:
            lm.agreed += 1
        else:
            lm.disagreed += 1
            lm.false_negative += 1  # expected this label, production didn't match

        # False positive: production action doesn't match any expected label.
        # We track this per production action across all cases.
        if not agreed:
            fp_key = f"FP:{prod_action}"
            fp_m = label_metrics[fp_key]
            fp_m.label = fp_key
            fp_m.total += 1
            fp_m.false_positive += 1

    result.per_label = dict(label_metrics)
    result.per_domain = {k: dict(v) for k, v in domain_counts.items()}
    return result


def _check_agreement(case: ReplayCase, expected: str, prod_action: str) -> bool:
    """Check if the production decision agrees with the expected label.

    Strict namespaced semantics (Phase 2):

      * ``action/X`` / legacy action labels  -> compare ONLY
        ``production_action == X``. No aliases.
      * ``outcome/X`` / legacy outcome labels -> compare ONLY against the
        observed objective facts (``observed_outcome``). Never consult the
        action. This fixes the historical bug where ``browser_rescued`` was
        folded into the ``BROWSER`` action alias set, so a production
        ``BROWSER`` with ``browser_success=false`` could be counted as
        agreement.
      * ``semantic/X`` -> never compared here (handled by advisor_evaluator).
    """
    ns, canon = split_label(expected)

    if ns in ("action", "legacy_action"):
        return action_matches(prod_action, canon)

    if ns in ("outcome", "legacy_outcome"):
        outcome = case.observed_outcome or {}
        # Carry deterministic reason/action so predicates like
        # INVALID_QUERY / RETURN_ERROR can be evaluated from the observed row.
        facts = dict(outcome)
        pd = case.production_decision or {}
        facts.setdefault("deterministic_reason", pd.get("deterministic_reason") or pd.get("reason") or "")
        facts.setdefault("production_action", pd.get("action") or prod_action)
        return outcome_holds(canon, facts, domain=case.domain or "fetch")

    # Unknown label: fall back to case-insensitive direct action equality.
    return bool(canon) and canon == prod_action.strip().upper()


def evaluate_from_store(domain: str | None = None, limit: int = 1000) -> EvaluationResult:
    """Load ReplayCases from the DecisionStore and evaluate them."""
    from . import decision_store

    rows = decision_store.load_replay_cases(domain=domain, limit=limit)
    cases = [ReplayCase.from_dict(r) for r in rows]
    return evaluate_cases(cases)
