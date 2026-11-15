"""Namespaced label taxonomy and strict outcome predicates.

Phase 2 separates three label namespaces so that an *action*, an *objective
outcome*, and a *semantic judgement* can never be confused:

  * ``action/<X>``     — what the deterministic system did. Compared ONLY
                         against ``production_action``. Never proves an
                         outcome.
  * ``outcome/<X>``    — an objective fact about what happened. Compared ONLY
                         against sanitized observed outcome scalars. Never
                         derived from the action itself.
  * ``semantic/<X>``   — a human (or strictly-allowed objective hard label)
                         judgement. May only be grounded by ``human_verified``
                         or an explicit objective hard-label subset; a Jev
                         prediction is never a source.

Legacy non-namespaced labels (``ACCEPT``, ``BROWSER``, ``browser_rescued`` ...)
from the pre-Phase-2 fixture set remain readable. Legacy *outcome* labels are
evaluated against observed outcome facts (never against the action), which
fixes the historical alias bug where ``BROWSER_RESCUED`` was folded into the
``BROWSER`` action alias set.

Thresholds are centralized here so they are not scattered as magic numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Centralized thresholds (counterfactual / scalar outcomes).
# ---------------------------------------------------------------------------
BROWSER_MATERIAL_GAIN_MIN_EXTRA_CHARS = 2000
BROWSER_MATERIAL_GAIN_MIN_RATIO = 2.0

LabelNamespace = Literal["action", "outcome", "semantic", "legacy_action", "legacy_outcome", "unknown"]

# ---------------------------------------------------------------------------
# Known vocabularies.
# ---------------------------------------------------------------------------
FETCH_ACTION_LABELS = frozenset(
    {
        "ACCEPT",
        "BROWSER",
        "CONTINUE_CONTENT",
        "PROVIDER_FALLBACK",
        "RETRY",
        "RETRY_LATER",
        "REQUIRE_AUTH",
        "STOP",
        "NONE",
    }
)

SEARCH_ACTION_LABELS = frozenset(
    {
        "ACCEPT",
        "TRY_NEXT_PROVIDER",
        "RETURN_EMPTY",
        "RETURN_ERROR",
        "STOP",
        "NONE",
    }
)

FETCH_OUTCOME_LABELS = frozenset(
    {
        "PRIMARY_COMPLETE",
        "CONTINUATION_REQUIRED",
        "BROWSER_RESCUED",
        "BROWSER_FAILED",
        "BROWSER_MATERIAL_GAIN",
        "PROVIDER_FALLBACK_RESCUED",
        "PROVIDER_FALLBACK_FAILED",
    }
)

SEARCH_OUTCOME_LABELS = frozenset(
    {
        "SEARCH_SUCCESS",
        "SEARCH_FALLBACK_RESCUED",
        "ALL_EMPTY",
        "ALL_FAILED",
        "INVALID_QUERY",
        "CIRCUIT_SKIP",
    }
)

SEMANTIC_LABELS = frozenset(
    {
        "RESULT_USABLE",
        "RESULT_NOT_USABLE",
        "RESULT_RELEVANT",
        "RESULT_NOT_RELEVANT",
        "NEEDS_MORE_CONTENT",
        "NO_MORE_CONTENT_NEEDED",
        "BROWSER_ESCALATION_WARRANTED",
        "BROWSER_ESCALATION_NOT_WARRANTED",
    }
)

# ---------------------------------------------------------------------------
# Allowed human-label vocabulary per Jev question (Phase 2.1.2 PART B).
#
# ``needs_escalation`` literally asks whether BROWSER escalation is warranted
# given the fetched page state. Its human ground truth MUST therefore be one of
# the two browser-escalation labels — the legacy ``semantic/needs_more_content``
# (generic "any recovery needed") is no longer an accepted human answer here.
# Strings are exact lowercase as written in the JSONL; ``import_human_labels``
# lower-cases/strips before membership.
# ---------------------------------------------------------------------------
HUMAN_LABELS_BY_QUESTION: dict[str, frozenset[str]] = {
    "needs_escalation": frozenset(
        {
            "semantic/browser_escalation_warranted",
            "semantic/browser_escalation_not_warranted",
        }
    ),
    "result_usable": frozenset(
        {
            "semantic/result_usable",
            "semantic/result_not_usable",
        }
    ),
    "result_relevant": frozenset(
        {
            "semantic/result_relevant",
            "semantic/result_not_relevant",
        }
    ),
}


def allowed_human_labels(question: str) -> frozenset[str]:
    """Return the allowed exact lowercase human labels for a Jev question.

    Unknown questions yield an empty frozenset (which rejects every label).
    """
    return HUMAN_LABELS_BY_QUESTION.get((question or "").strip(), frozenset())


# Legacy outcome aliases (pre-namespace fixtures) -> canonical outcome.
_LEGACY_OUTCOME_ALIASES = {
    "BROWSER_RESCUED": "BROWSER_RESCUED",
    "BROWSER_SUCCESS": "BROWSER_RESCUED",
    "FALLBACK_RESCUED": "PROVIDER_FALLBACK_RESCUED",
    "FALLBACK_SUCCESS": "PROVIDER_FALLBACK_RESCUED",
    "ALL_EMPTY": "ALL_EMPTY",
    "EMPTY_RESULT": "ALL_EMPTY",
    "ALL_FAILED": "ALL_FAILED",
    "ALL_BACKENDS_FAILED": "ALL_FAILED",
    "CONTINUATION_AVAILABLE": "CONTINUATION_REQUIRED",
    "HAS_MORE": "CONTINUATION_REQUIRED",
    "SEARCH_SUCCESS": "SEARCH_SUCCESS",
}


def split_label(label: str) -> tuple[LabelNamespace, str]:
    """Split a (possibly namespaced) label into (namespace, canonical upper).

    ``action/BROWSER``      -> ("action", "BROWSER")
    ``outcome/browser_rescued`` -> ("outcome", "BROWSER_RESCUED")
    ``semantic/result_usable``  -> ("semantic", "RESULT_USABLE")
    ``ACCEPT``              -> ("legacy_action" | "legacy_outcome" | "unknown", canon)
    """
    raw = (label or "").strip()
    if not raw:
        return ("unknown", "")
    if "/" in raw:
        ns, _, tail = raw.partition("/")
        canon = tail.strip().upper().replace("-", "_").replace(" ", "_")
        ns_l = ns.strip().lower()
        if ns_l in ("action", "outcome", "semantic"):
            return (ns_l, canon)  # type: ignore[return-value]
        return ("unknown", canon)

    canon = raw.upper().replace("-", "_").replace(" ", "_")
    if canon in FETCH_ACTION_LABELS or canon in SEARCH_ACTION_LABELS:
        return ("legacy_action", canon)
    if canon in FETCH_OUTCOME_LABELS or canon in SEARCH_OUTCOME_LABELS:
        return ("legacy_outcome", canon)
    if canon in SEMANTIC_LABELS:
        return ("semantic", canon)
    if canon in _LEGACY_OUTCOME_ALIASES:
        return ("legacy_outcome", _LEGACY_OUTCOME_ALIASES[canon])
    return ("unknown", canon)


# ---------------------------------------------------------------------------
# Strict predicate helpers (operate on sanitized outcome_features scalars).
# ---------------------------------------------------------------------------


def _bool(facts: dict[str, Any], *keys: str) -> bool | None:
    """Return the first truthy/falsy boolean-ish value, or None if unset."""
    for k in keys:
        if k in facts and facts[k] is not None:
            v = facts[k]
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            if isinstance(v, str):
                return v.strip().lower() in ("1", "true", "yes", "ok", "success")
    return None


def _scalar(facts: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in facts and facts[k] is not None:
            return facts[k]
    return None


def primary_extraction_ok(facts: dict[str, Any]) -> bool:
    v = _bool(facts, "primary_extraction_success", "extraction_success")
    return bool(v)


def primary_transport_ok(facts: dict[str, Any]) -> bool:
    """Best-effort structural 'primary transport reached a usable page'."""
    group = str(_scalar(facts, "http_status_group") or "")
    if group in ("4xx", "5xx", "3xx"):
        return False
    status = str(_scalar(facts, "primary_status", "status") or "").lower()
    if status in ("error", "failed", "timeout", "blocked", "soft_block"):
        return False
    return True


def primary_hard_signal(facts: dict[str, Any]) -> str:
    """Return the hard recovery signal on the primary attempt, or ''."""
    sig = str(_scalar(facts, "primary_hard_signal") or "").upper()
    if sig:
        return sig
    reason = str(_scalar(facts, "deterministic_reason", "primary_reason") or "").upper()
    if reason in ("JS_REQUIRED", "SOFT_BLOCK", "TRANSPORT_FAILURE", "TIMEOUT"):
        return reason
    if not primary_transport_ok(facts):
        return "TRANSPORT_FAILURE"
    return ""


def primary_objectively_failed(facts: dict[str, Any]) -> bool:
    """Primary failed in a way that makes browser/fallback recovery meaningful."""
    sig = primary_hard_signal(facts)
    if sig in ("JS_REQUIRED", "SOFT_BLOCK", "TRANSPORT_FAILURE", "TIMEOUT"):
        return True
    if not primary_extraction_ok(facts):
        return True
    return not primary_transport_ok(facts)


# ---------------------------------------------------------------------------
# Fetch outcome predicates.
# ---------------------------------------------------------------------------


def fetch_primary_complete(facts: dict[str, Any]) -> bool:
    truncated = bool(_bool(facts, "truncated_by_output_limit", "truncated"))
    has_more = bool(_bool(facts, "continuation_has_more", "continuation_available"))
    sig = primary_hard_signal(facts)
    return (
        primary_extraction_ok(facts)
        and primary_transport_ok(facts)
        and sig not in ("JS_REQUIRED", "SOFT_BLOCK", "TRANSPORT_FAILURE", "TIMEOUT")
        and not truncated
        and not has_more
    )


def fetch_continuation_required(facts: dict[str, Any]) -> bool:
    truncated = bool(_bool(facts, "truncated_by_output_limit", "truncated"))
    has_more = bool(_bool(facts, "continuation_has_more", "continuation_available"))
    return truncated and has_more


def fetch_browser_rescued(facts: dict[str, Any]) -> bool:
    attempted = bool(_bool(facts, "browser_attempted", "browser_used"))
    ok = bool(_bool(facts, "browser_success"))
    # Strict: primary must have objectively failed AND browser actually succeeded.
    return attempted and ok and primary_objectively_failed(facts)


def fetch_browser_failed(facts: dict[str, Any]) -> bool:
    attempted = bool(_bool(facts, "browser_attempted", "browser_used"))
    ok = bool(_bool(facts, "browser_success"))
    return attempted and not ok


def fetch_browser_material_gain(facts: dict[str, Any]) -> bool:
    """Counterfactual scalar gain. NOT equivalent to 'browser was required'."""
    if not bool(_bool(facts, "browser_success")):
        return False
    browser_chars = float(_scalar(facts, "browser_content_chars", "final_content_chars") or 0)
    primary_chars = float(_scalar(facts, "primary_content_chars") or 0)
    extra = browser_chars - primary_chars
    if extra < BROWSER_MATERIAL_GAIN_MIN_EXTRA_CHARS:
        return False
    if primary_chars <= 0:
        # If primary produced nothing, any non-trivial browser content is gain.
        return browser_chars >= BROWSER_MATERIAL_GAIN_MIN_EXTRA_CHARS
    return browser_chars >= primary_chars * BROWSER_MATERIAL_GAIN_MIN_RATIO


def fetch_fallback_rescued(facts: dict[str, Any]) -> bool:
    attempted = bool(_bool(facts, "fallback_attempted", "fallback_used"))
    ok = bool(_bool(facts, "fallback_success"))
    return attempted and ok and primary_objectively_failed(facts)


def fetch_fallback_failed(facts: dict[str, Any]) -> bool:
    attempted = bool(_bool(facts, "fallback_attempted", "fallback_used"))
    ok = bool(_bool(facts, "fallback_success"))
    return attempted and not ok


# ---------------------------------------------------------------------------
# Search outcome predicates.
# ---------------------------------------------------------------------------


def search_success(facts: dict[str, Any]) -> bool:
    return int(_scalar(facts, "result_count") or 0) > 0


def search_fallback_rescued(facts: dict[str, Any]) -> bool:
    """Prior attempt(s) EMPTY/hard error, then a provider ACCEPTed with results."""
    if not search_success(facts):
        return False
    fallback_count = int(_scalar(facts, "fallback_count") or 0)
    attempts = facts.get("attempt_summary")
    if isinstance(attempts, list) and attempts:
        prior_had_failure = any(
            str(a.get("outcome", "")).upper() in ("ERROR", "EMPTY") for a in attempts[:-1] if isinstance(a, dict)
        )
        return prior_had_failure or fallback_count > 0
    return fallback_count > 0


def search_all_empty(facts: dict[str, Any]) -> bool:
    status = str(_scalar(facts, "status") or "").lower()
    return status == "empty" or int(_scalar(facts, "result_count") or -1) == 0 and status != "success"


def search_all_failed(facts: dict[str, Any]) -> bool:
    status = str(_scalar(facts, "status") or "").lower()
    action = str(_scalar(facts, "production_action", "deterministic_action") or "").upper()
    return status == "error" or action == "RETURN_ERROR"


def search_invalid_query(facts: dict[str, Any]) -> bool:
    reason = str(_scalar(facts, "deterministic_reason", "reason") or "").upper()
    action = str(_scalar(facts, "production_action", "deterministic_action") or "").upper()
    return action == "STOP" and "INVALID_QUERY" in reason


def search_circuit_skip(facts: dict[str, Any]) -> bool:
    return int(_scalar(facts, "circuit_skips") or 0) > 0


# Map canonical outcome label -> predicate for fetch / search.
_FETCH_OUTCOME_PREDICATES = {
    "PRIMARY_COMPLETE": fetch_primary_complete,
    "CONTINUATION_REQUIRED": fetch_continuation_required,
    "BROWSER_RESCUED": fetch_browser_rescued,
    "BROWSER_FAILED": fetch_browser_failed,
    "BROWSER_MATERIAL_GAIN": fetch_browser_material_gain,
    "PROVIDER_FALLBACK_RESCUED": fetch_fallback_rescued,
    "PROVIDER_FALLBACK_FAILED": fetch_fallback_failed,
}

_SEARCH_OUTCOME_PREDICATES = {
    "SEARCH_SUCCESS": search_success,
    "SEARCH_FALLBACK_RESCUED": search_fallback_rescued,
    "ALL_EMPTY": search_all_empty,
    "ALL_FAILED": search_all_failed,
    "INVALID_QUERY": search_invalid_query,
    "CIRCUIT_SKIP": search_circuit_skip,
}


def outcome_holds(canonical: str, facts: dict[str, Any], domain: str = "fetch") -> bool:
    """Whether the objective outcome fact holds in the observed scalars.

    Never consults production_action. Returns False when the predicate is
    unknown/undefined.
    """
    canonical = canonical.upper()
    pred = _FETCH_OUTCOME_PREDICATES.get(canonical) or _SEARCH_OUTCOME_PREDICATES.get(canonical)
    if pred is None:
        return False
    try:
        return bool(pred(facts))
    except Exception:
        return False


def action_matches(production_action: str, expected_canonical: str) -> bool:
    """Strict action comparison: exact upper-cased equality. No aliases."""
    if not production_action or not expected_canonical:
        return False
    return production_action.strip().upper() == expected_canonical.strip().upper()


@dataclass(frozen=True)
class LabelTaxonomy:
    """Static export of the taxonomy for reports."""

    fetch_actions: tuple[str, ...] = field(default_factory=lambda: tuple(sorted(FETCH_ACTION_LABELS)))
    search_actions: tuple[str, ...] = field(default_factory=lambda: tuple(sorted(SEARCH_ACTION_LABELS)))
    fetch_outcomes: tuple[str, ...] = field(default_factory=lambda: tuple(sorted(FETCH_OUTCOME_LABELS)))
    search_outcomes: tuple[str, ...] = field(default_factory=lambda: tuple(sorted(SEARCH_OUTCOME_LABELS)))
    semantic: tuple[str, ...] = field(default_factory=lambda: tuple(sorted(SEMANTIC_LABELS)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": {
                "fetch": [f"action/{x.lower()}" for x in self.fetch_actions],
                "search": [f"action/{x.lower()}" for x in self.search_actions],
            },
            "outcome": {
                "fetch": [f"outcome/{x.lower()}" for x in self.fetch_outcomes],
                "search": [f"outcome/{x.lower()}" for x in self.search_outcomes],
            },
            "semantic": [f"semantic/{x.lower()}" for x in self.semantic],
        }
