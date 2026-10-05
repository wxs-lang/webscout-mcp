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

import json
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
    "browser_gain_chars",
    "browser_status",
    "browser_counterfactual_observed",
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


def has_browser_counterfactual(facts: dict[str, Any]) -> bool:
    """True only when a browser counterfactual was ACTUALLY observed.

    "The browser never ran" must NOT be read as "the browser ran and found no
    gain". A counterfactual was observed when EITHER:
      * ``browser_counterfactual_observed`` is truthy (merged from the run's
        ``browser-counterfactual.jsonl`` artifact), OR
      * the explicit observation triple is present: ``browser_status``,
        ``browser_content_chars`` (or ``browser_chars``) and
        ``browser_extraction_success``. Presence of the triple means the browser
        backend actually executed (success OR explicit error) in the sweep.
    """
    if facts.get("browser_counterfactual_observed"):
        return True
    status = facts.get("browser_status")
    chars = facts.get("browser_content_chars", facts.get("browser_chars"))
    ext = facts.get("browser_extraction_success")
    triple_present = status is not None and chars is not None and ext is not None
    return bool(triple_present)


def jev_needs_escalation_objective(facts: dict[str, Any]) -> ObjectiveLabelResult:
    """YES: primary hard failure AND actual recovery (browser/fallback) rescued,
    OR an explicit continuation-required. NO: primary structurally complete AND
    a browser counterfactual was ACTUALLY observed AND the browser neither rescued
    nor produced a material gain. Otherwise AMBIGUOUS.

    Critically, when no browser counterfactual was observed we MUST NOT treat
    "the browser never ran" as "the browser ran with no gain": the result is
    then AMBIGUOUS with ``ambiguity_reason="missing_browser_counterfactual"``.
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
    if not has_browser_counterfactual(facts):
        # "Browser never ran" is not evidence of "browser ran, no gain".
        return ObjectiveLabelResult(
            label=None,
            confidence=0.0,
            evidence=_evidence(facts, _FETCH_EVIDENCE_KEYS),
            is_objective=False,
            ambiguity_reason="missing_browser_counterfactual",
        )
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


# ---------------------------------------------------------------------------
# Phase 2.1: materialize objective ReplayCases for one evaluation run.
# ---------------------------------------------------------------------------

# Questions that MAY receive an objective label. result_relevant is
# deliberately ABSENT: a search-success / result_count>0 is never relevance
# ground truth.
_OBJECTIVE_QUESTIONS: tuple[tuple[str, Any], ...] = (
    ("needs_escalation", jev_needs_escalation_objective),
    ("result_usable", jev_result_usable_objective),
)


def _load_browser_counterfactual_index(
    run_id: str,
    browser_counterfactual_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load the run's ``browser-counterfactual.jsonl`` keyed by ``source_trace_id``.

    Join authority is ``source_trace_id`` (the production trace minted by the
    fetch path) — NOT a URL hash. The default location is the run directory next
    to the decision DB; an explicit path may be supplied. Any read failure yields
    an empty index (events then keep facts WITHOUT browser evidence, so the
    needs_escalation label is correctly ambiguous rather than a fake NO).
    """
    from pathlib import Path

    from . import decision_store

    index: dict[str, dict[str, Any]] = {}
    path: Path | None = None
    if browser_counterfactual_path:
        path = Path(browser_counterfactual_path)
    else:
        # Run dir = parent of the configured decision DB.
        path = decision_store.db_path().parent / "browser-counterfactual.jsonl"
    if not path.exists():
        return index
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                trace = row.get("source_trace_id")
                if trace:
                    index[str(trace)] = row
    except OSError:
        return {}
    return index


def _merged_objective_facts(
    event: dict[str, Any],
    cf_by_trace: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build evaluation-only facts for one event, merging the browser CF row.

    The merge exists ONLY during materialization for objective labeling. It is
    never written back to the production DecisionEvent / outcome_features /
    telemetry. Only sanitized scalars are merged; the raw browser body / URL
    path never enters a label.
    """
    facts = dict(event.get("outcome_features") or {})
    cf = cf_by_trace.get(event.get("trace_id"))
    if not cf:
        return facts
    # Artifact uses browser_chars / gain; map to the scalar names the objective
    # predicates read.
    browser_status = cf.get("browser_status")
    browser_chars = cf.get("browser_chars")
    browser_extraction_success = cf.get("browser_extraction_success")
    merged = dict(facts)
    merged["browser_counterfactual_observed"] = True
    if browser_status is not None:
        merged["browser_status"] = browser_status
    if browser_chars is not None:
        merged["browser_content_chars"] = browser_chars
    if cf.get("gain") is not None:
        merged["browser_gain_chars"] = cf.get("gain")
    if browser_extraction_success is not None:
        merged["browser_extraction_success"] = bool(browser_extraction_success)
    # Derived safe booleans so the deterministic predicates can see the observed
    # browser execution. The browser actually ran in the CF sweep; whether it
    # succeeded is encoded by browser_status.
    merged["browser_attempted"] = True
    merged["browser_success"] = bool(browser_status == "success")
    return merged


def materialize_objective_replay_cases(
    run_id: str,
    browser_counterfactual_path: str | None = None,
) -> int:
    """Materialize objective ReplayCases for one run (OFFLINE EVALUATION CLI).

    Reads that run's DecisionEvents AND its ``browser-counterfactual.jsonl``
    artifact (default: run dir next to the decision DB; override via
    ``browser_counterfactual_path``). Each CF row is joined to a DecisionEvent by
    ``(run_id, source_trace_id) == event(run_id, trace_id)`` — ``source_trace_id``
    is the authority, never a URL hash. Joined events get MERGED evaluation facts
    (see :func:`_merged_objective_facts`) used ONLY for objective labeling.

    For each event, derives objective Jev-question ground truth from its outcome
    facts for ``needs_escalation`` and ``result_usable`` ONLY. ``result_relevant``
    is never materialized — a SEARCH_SUCCESS / result_count>0 must never create a
    semantic case.

    Idempotent: case_ids are deterministic ``<event_id>:<question>`` and rows
    are INSERT OR REPLACE'd, so re-runs never duplicate. Returns the number of
    objective cases written.

    Lazily imports ``decision_store`` / ``ReplayCase`` to avoid import cycles.
    This is evaluation-only: it MUST NOT be called on the production path.
    """
    import time

    from . import decision_store
    from .replay_case import ReplayCase

    cf_by_trace = _load_browser_counterfactual_index(run_id, browser_counterfactual_path)

    written = 0
    for event in decision_store.load_events_for_run(run_id):
        facts = _merged_objective_facts(event, cf_by_trace)
        for question, objective_fn in _OBJECTIVE_QUESTIONS:
            result = objective_fn(facts)
            if not result.is_objective or not result.label:
                continue
            case = ReplayCase(
                case_id=f"{event.get('event_id', '')}:{question}",
                run_id=event.get("run_id", "") or run_id,
                trace_id=event.get("trace_id", "") or "",
                domain=event.get("domain", "fetch") or "fetch",
                input_features=dict(event.get("request_features") or {}),
                observed_outcome=facts,
                production_decision={
                    "deterministic_reason": event.get("deterministic_reason", ""),
                    "deterministic_action": event.get("deterministic_action", ""),
                    "production_action": event.get("production_action", ""),
                    "production_outcome": event.get("production_outcome", ""),
                    "question": question,
                },
                expected_label=result.label,
                label_source=LabelSource.OBJECTIVE_OUTCOME,
                label_confidence=float(result.confidence),
                label_time=time.time(),
                notes="",
            )
            if decision_store.record_replay_case(case):
                written += 1
    return written
