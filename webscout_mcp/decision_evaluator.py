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
    per_label: dict[str, LabelMetrics] = field(default_factory=dict)
    per_domain: dict[str, dict[str, int]] = field(default_factory=dict)
    disagreements: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "covered_cases": self.covered_cases,
            "uncovered_cases": self.uncovered_cases,
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

    Supports both action labels (direct match) and outcome labels
    (checked against observed_outcome).
    """
    expected_upper = expected.upper().replace("-", "_").replace(" ", "_")

    # Direct action match.
    action_aliases = {
        "ACCEPT": {"ACCEPT", "SUCCESS", "OK"},
        "BROWSER": {"BROWSER", "BROWSER_RESCUED", "BROWSER_SUCCESS"},
        "CONTINUE_CONTENT": {"CONTINUE_CONTENT", "CONTINUATION", "TRUNCATED"},
        "STOP": {"STOP", "INVALID_QUERY", "TERMINAL"},
        "TRY_NEXT_PROVIDER": {"TRY_NEXT_PROVIDER", "FALLBACK", "NEXT_PROVIDER"},
        "RETURN_EMPTY": {"RETURN_EMPTY", "ALL_EMPTY", "EMPTY"},
        "RETURN_ERROR": {"RETURN_ERROR", "ALL_FAILED", "ERROR"},
        "PROVIDER_FALLBACK": {"PROVIDER_FALLBACK", "FALLBACK_RESCUED"},
        "RETRY": {"RETRY", "RETRY_LATER"},
        "REQUIRE_AUTH": {"REQUIRE_AUTH", "AUTH"},
        "NONE": {"NONE", "AMBIGUOUS", "NO_ACTION"},
    }

    for canonical, aliases in action_aliases.items():
        if expected_upper in aliases:
            return prod_action.upper() == canonical or prod_action.upper() in aliases

    # Outcome labels: check observed_outcome.
    outcome = case.observed_outcome or {}
    if expected_upper in {"BROWSER_RESCUED", "BROWSER_SUCCESS"}:
        return bool(outcome.get("browser_success") or outcome.get("browser_used"))
    if expected_upper in {"FALLBACK_RESCUED", "FALLBACK_SUCCESS"}:
        return bool(outcome.get("fallback_used") and outcome.get("status") in ("success", "ok"))
    if expected_upper in {"ALL_EMPTY", "EMPTY_RESULT"}:
        return bool(outcome.get("status") == "empty" or outcome.get("result_count", 1) == 0)
    if expected_upper in {"ALL_FAILED", "ALL_BACKENDS_FAILED"}:
        return bool(outcome.get("status") == "error")
    if expected_upper in {"CONTINUATION_AVAILABLE", "HAS_MORE"}:
        return bool(outcome.get("continuation_available") or outcome.get("truncated"))
    if expected_upper in {"CACHE_HIT", "SERVED_FROM_CACHE"}:
        return bool(outcome.get("cache_hit"))

    # Fallback: case-insensitive exact match.
    return expected_upper == prod_action.upper()


def evaluate_from_store(domain: str | None = None, limit: int = 1000) -> EvaluationResult:
    """Load ReplayCases from the DecisionStore and evaluate them."""
    from . import decision_store

    rows = decision_store.load_replay_cases(domain=domain, limit=limit)
    cases = [ReplayCase.from_dict(r) for r in rows]
    return evaluate_cases(cases)
