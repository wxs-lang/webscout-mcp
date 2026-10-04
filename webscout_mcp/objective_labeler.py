"""Objective outcome labeler (Phase 2).

Produces ``outcome/*`` labels strictly from *production facts*,
*counterfactual facts*, and *deterministic metadata*. It MUST NOT read Jev
decisions or probabilities — a Jev prediction can never become a ground-truth
label. Ambiguous cases yield ``label=None`` (no fake YES/NO).

Each emitted label carries:
  * ``label``           namespaced outcome label (e.g. ``outcome/browser_rescued``)
  * ``label_source``    always ``objective_outcome``
  * ``label_confidence`` 0..1
  * ``evidence``        sanitized scalars only (no body, no query, no URL path)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .decision_event import LabelSource
from .labels import (
    fetch_browser_failed,
    fetch_browser_material_gain,
    fetch_browser_rescued,
    fetch_continuation_required,
    fetch_fallback_failed,
    fetch_fallback_rescued,
    fetch_primary_complete,
    search_all_empty,
    search_all_failed,
    search_circuit_skip,
    search_fallback_rescued,
    search_invalid_query,
    search_success,
)


@dataclass(frozen=True)
class ObjectiveLabelResult:
    """One objective label decision for one event."""

    label: str | None
    confidence: float
    evidence: dict[str, Any]
    is_objective: bool
    ambiguity_reason: str | None = None
    label_source: str = LabelSource.OBJECTIVE_OUTCOME.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "label_source": self.label_source,
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
            "is_objective": self.is_objective,
            "ambiguity_reason": self.ambiguity_reason,
        }


def _evidence(facts: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """Pick only the requested sanitized scalars. Never passes through free text."""
    out: dict[str, Any] = {}
    for k in keys:
        if k in facts and facts[k] is not None:
            v = facts[k]
            # Evidence must remain scalar; drop nested blobs defensively.
            if isinstance(v, (str, int, float, bool)):
                out[k] = v
            elif isinstance(v, list):
                out[k] = [a for a in v if isinstance(a, (str, int, float, bool))][:8]
    return out


# Evidence scalars collected per label type.
_FETCH_EVIDENCE_KEYS = (
    "primary_status",
    "http_status_group",
    "http_status_code",
    "primary_content_chars",
    "final_content_chars",
    "content_gain_chars",
    "truncated",
    "continuation_available",
    "browser_attempted",
    "browser_success",
    "browser_content_chars",
    "fallback_attempted",
    "fallback_success",
    "primary_extraction_success",
    "final_extraction_success",
    "primary_hard_signal",
)

_SEARCH_EVIDENCE_KEYS = (
    "status",
    "result_count",
    "provider_attempt_count",
    "fallback_count",
    "circuit_skips",
    "deterministic_reason",
    "production_action",
)


def label_fetch_outcomes(facts: dict[str, Any]) -> list[ObjectiveLabelResult]:
    """Emit all applicable Fetch objective outcome labels for one event.

    Facts = the event's ``outcome_features`` (plus optional
    ``deterministic_reason``). Never reads Jev.
    """
    out: list[ObjectiveLabelResult] = []

    def emit(canonical: str, holds: bool, confidence: float, ambiguity: str | None = None) -> None:
        if holds:
            out.append(
                ObjectiveLabelResult(
                    label=f"outcome/{canonical.lower()}",
                    confidence=confidence,
                    evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
                    is_objective=True,
                )
            )
        elif ambiguity is not None:
            out.append(
                ObjectiveLabelResult(
                    label=None,
                    confidence=0.0,
                    evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
                    is_objective=False,
                    ambiguity_reason=ambiguity,
                )
            )

    emit("primary_complete", fetch_primary_complete(facts), 0.95)
    emit("continuation_required", fetch_continuation_required(facts), 0.99)
    emit("browser_rescued", fetch_browser_rescued(facts), 0.9)
    emit("browser_failed", fetch_browser_failed(facts), 0.9)
    emit("browser_material_gain", fetch_browser_material_gain(facts), 0.85)
    emit("provider_fallback_rescued", fetch_fallback_rescued(facts), 0.9)
    emit("provider_fallback_failed", fetch_fallback_failed(facts), 0.9)

    # If nothing objective fired, mark ambiguous (do not fabricate a label).
    if not out:
        out.append(
            ObjectiveLabelResult(
                label=None,
                confidence=0.0,
                evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
                is_objective=False,
                ambiguity_reason="no_objective_outcome_signal",
            )
        )
    return out


def label_search_outcomes(facts: dict[str, Any]) -> list[ObjectiveLabelResult]:
    """Emit all applicable Search objective outcome labels for one event.

    Note: ``search_success`` (result_count > 0) is NOT relevance ground truth.
    """
    out: list[ObjectiveLabelResult] = []

    def emit(canonical: str, holds: bool, confidence: float) -> None:
        if holds:
            out.append(
                ObjectiveLabelResult(
                    label=f"outcome/{canonical.lower()}",
                    confidence=confidence,
                    evidence=_evidence(facts, _SEARCH_EVIDENCE_KEYS),
                    is_objective=True,
                )
            )

    emit("search_success", search_success(facts), 0.9)
    emit("search_fallback_rescued", search_fallback_rescued(facts), 0.9)
    emit("all_empty", search_all_empty(facts), 0.95)
    emit("all_failed", search_all_failed(facts), 0.95)
    emit("invalid_query", search_invalid_query(facts), 0.99)
    emit("circuit_skip", search_circuit_skip(facts), 0.99)

    if not out:
        out.append(
            ObjectiveLabelResult(
                label=None,
                confidence=0.0,
                evidence=_evidence(facts, _SEARCH_EVIDENCE_KEYS),
                is_objective=False,
                ambiguity_reason="no_objective_outcome_signal",
            )
        )
    return out


def label_outcomes(domain: str, facts: dict[str, Any]) -> list[ObjectiveLabelResult]:
    if domain == "search":
        return label_search_outcomes(facts)
    return label_fetch_outcomes(facts)


# ---------------------------------------------------------------------------
# Jev-question objective subsets (strict).
# ---------------------------------------------------------------------------
#
# These map a Jev question to an objective YES/NO/AMBIGUOUS decision. They are
# deliberately conservative: only a strict objective subset may be labeled;
# everything else is AMBIGUOUS and excluded from accuracy.


def jev_needs_escalation_objective(facts: dict[str, Any]) -> ObjectiveLabelResult:
    """YES: primary hard failure AND actual recovery (browser/fallback) rescued,
    OR an explicit continuation-required. NO: primary structurally complete AND
    counterfactual browser had no rescue / no material gain. Otherwise AMBIGUOUS.
    """
    rescued = fetch_browser_rescued(facts) or fetch_fallback_rescued(facts)
    continuation = fetch_continuation_required(facts)
    if rescued or continuation:
        return ObjectiveLabelResult(
            label="semantic/needs_more_content",
            confidence=0.8,
            evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
            is_objective=True,
        )
    primary_ok = fetch_primary_complete(facts)
    browser_no_gain = (not fetch_browser_material_gain(facts)) and (not fetch_browser_rescued(facts))
    if primary_ok and browser_no_gain:
        return ObjectiveLabelResult(
            label="semantic/no_more_content_needed",
            confidence=0.7,
            evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
            is_objective=True,
        )
    return ObjectiveLabelResult(
        label=None,
        confidence=0.0,
        evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
        is_objective=False,
        ambiguity_reason="needs_escalation_objective_subset_inconclusive",
    )


def jev_result_usable_objective(facts: dict[str, Any]) -> ObjectiveLabelResult:
    """Strict objective YES/NO for result_usable.

    NO ground truth: transport failure / empty extraction / explicit block.
    Otherwise AMBIGUOUS (needs human). We do NOT treat HTTP 200 + chars>N as
    usable.
    """
    hard_unusable = (
        "TRANSPORT_FAILURE" in str(facts.get("primary_hard_signal", "")).upper()
        or "SOFT_BLOCK" in str(facts.get("primary_hard_signal", "")).upper()
        or not bool(facts.get("final_extraction_success", facts.get("extraction_success", True)))
    )
    status = str(facts.get("status", "")).lower()
    if hard_unusable or status in ("error", "failed", "blocked"):
        return ObjectiveLabelResult(
            label="semantic/result_not_usable",
            confidence=0.9,
            evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
            is_objective=True,
        )
    # Primary structurally complete is a weak structural NO-to-unusable, but the
    # prompt forbids treating 200+chars as usable. Only emit when extraction
    # clearly succeeded and no hard signal.
    return ObjectiveLabelResult(
        label=None,
        confidence=0.0,
        evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
        is_objective=False,
        ambiguity_reason="result_usable_requires_human_label",
    )


# result_relevant has NO objective subset: only human_verified enters accuracy.
def jev_result_relevant_objective(facts: dict[str, Any]) -> ObjectiveLabelResult:  # noqa: ARG001
    """result_relevant can never be objective (result_count>0 is not relevance)."""
    return ObjectiveLabelResult(
        label=None,
        confidence=0.0,
        evidence={},
        is_objective=False,
        ambiguity_reason="result_relevant_is_human_only",
    )
