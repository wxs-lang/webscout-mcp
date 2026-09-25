"""ReplayCase: an offline, labelable unit for evaluating decision rules.

A ReplayCase captures the *input features* and *observed outcome* of a real
production decision, plus an *expected label* derived from a trusted source
(deterministic fixture, human verification, or objective outcome). It is the
unit of work for the offline evaluator.

Jev predictions are NEVER a valid label_source. They may be joined for
comparison but cannot mark a case as "correct".
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .decision_event import LabelSource

_VALID_LABEL_SOURCES = {e.value for e in LabelSource}


def _validate_label_source(value: Any) -> LabelSource:
    """Strict validation: invalid label_source raises ValueError.

    No silent fallback to OBJECTIVE_OUTCOME — that would let jev_verified
    or typos masquerade as trusted labels.
    """
    if isinstance(value, LabelSource):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"label_source must be a non-empty string, got {value!r}")
    if value not in _VALID_LABEL_SOURCES:
        raise ValueError(
            f"Invalid label_source {value!r}. Must be one of: {sorted(_VALID_LABEL_SOURCES)}. "
            "jev_verified is explicitly rejected."
        )
    return LabelSource(value)


@dataclass
class ReplayCase:
    """A single offline replay/evaluation case.

    Attributes:
        case_id: stable unique id.
        domain: "fetch" or "search".
        input_features: sanitized request features (same shape as DecisionEvent.request_features).
        observed_outcome: sanitized outcome features (same shape as DecisionEvent.outcome_features).
        production_decision: the deterministic decision that was made in production
            (reason + action + outcome).
        expected_label: trusted label for this case.
        label_source: where the label came from (never jev_verified). Strictly validated.
        label_confidence: 0..1, how confident the label source is.
        label_time: UTC epoch when the label was last set (None if not yet labeled).
        notes: free-text annotation (scrubbed of secrets at store time).
        created_at: epoch seconds.
    """

    case_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    domain: str = "fetch"
    input_features: dict[str, Any] = field(default_factory=dict)
    observed_outcome: dict[str, Any] = field(default_factory=dict)
    production_decision: dict[str, Any] = field(default_factory=dict)
    expected_label: str = ""
    label_source: LabelSource = LabelSource.OBJECTIVE_OUTCOME
    label_confidence: float = 1.0
    label_time: float | None = None
    notes: str = ""
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.label_source = _validate_label_source(self.label_source)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["label_source"] = self.label_source.value if isinstance(self.label_source, LabelSource) else self.label_source
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplayCase:
        """Strict: invalid label_source raises ValueError (no silent fallback)."""
        label_source = _validate_label_source(data.get("label_source", "objective_outcome"))
        return cls(
            case_id=data.get("case_id", str(uuid.uuid4())),
            domain=data.get("domain", "fetch"),
            input_features=dict(data.get("input_features", {})),
            observed_outcome=dict(data.get("observed_outcome", {})),
            production_decision=dict(data.get("production_decision", {})),
            expected_label=data.get("expected_label", ""),
            label_source=label_source,
            label_confidence=float(data.get("label_confidence", 1.0)),
            label_time=data.get("label_time"),
            notes=data.get("notes", ""),
            created_at=float(data.get("created_at", time.time())),
        )
