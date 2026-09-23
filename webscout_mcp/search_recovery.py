"""Deterministic Search Recovery classifier (v1.4.0 Phase 2).

Pure, deterministic classification of a search provider outcome into a
stable (reason, recommended_action) pair. This is NOT an executor and
NOT controlled by Jev: it only labels outcomes for observability and
for Phase 3 (Unified Search Recovery Orchestration).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import StandardErrorCode
from .search_provider import SearchFailureKind, SearchResponse, SearchStatus


class SearchRecoveryReason(str, Enum):
    """Stable reason labels for a search provider outcome or final result."""

    RESULT_AVAILABLE = "RESULT_AVAILABLE"
    EMPTY_RESULT = "EMPTY_RESULT"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_ERROR = "AUTH_ERROR"
    PARSER_FAILURE = "PARSER_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    SERVER_ERROR = "SERVER_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_QUERY = "INVALID_QUERY"
    ALL_EMPTY = "ALL_EMPTY"
    ALL_FAILED = "ALL_FAILED"
    UNKNOWN = "UNKNOWN"


class SearchRecoveryAction(str, Enum):
    """Recommended next action. TRY_NEXT_PROVIDER is never same-provider retry."""

    ACCEPT = "ACCEPT"
    TRY_NEXT_PROVIDER = "TRY_NEXT_PROVIDER"
    RETURN_EMPTY = "RETURN_EMPTY"
    RETURN_ERROR = "RETURN_ERROR"
    STOP = "STOP"
    NONE = "NONE"


# failure_kind -> (reason, action)
_KIND_MAP: dict[SearchFailureKind, tuple[SearchRecoveryReason, SearchRecoveryAction]] = {
    SearchFailureKind.TIMEOUT: (SearchRecoveryReason.TIMEOUT, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    SearchFailureKind.RATE_LIMITED: (SearchRecoveryReason.RATE_LIMITED, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    SearchFailureKind.AUTH: (SearchRecoveryReason.AUTH_ERROR, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    SearchFailureKind.PARSER: (SearchRecoveryReason.PARSER_FAILURE, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    SearchFailureKind.NETWORK: (SearchRecoveryReason.NETWORK_FAILURE, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    SearchFailureKind.SERVER: (SearchRecoveryReason.SERVER_ERROR, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    SearchFailureKind.CONFIG: (SearchRecoveryReason.CONFIG_ERROR, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    SearchFailureKind.PROVIDER: (SearchRecoveryReason.PROVIDER_ERROR, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    SearchFailureKind.INVALID_REQUEST: (SearchRecoveryReason.INVALID_QUERY, SearchRecoveryAction.STOP),
}

# StandardErrorCode fallback when failure_kind is absent.
_CODE_MAP: dict[StandardErrorCode, tuple[SearchRecoveryReason, SearchRecoveryAction]] = {
    StandardErrorCode.SEARCH_TIMEOUT: (SearchRecoveryReason.TIMEOUT, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    StandardErrorCode.FETCH_TIMEOUT: (SearchRecoveryReason.TIMEOUT, SearchRecoveryAction.TRY_NEXT_PROVIDER),
    StandardErrorCode.SEARCH_RATE_LIMITED: (
        SearchRecoveryReason.RATE_LIMITED,
        SearchRecoveryAction.TRY_NEXT_PROVIDER,
    ),
    StandardErrorCode.FETCH_RATE_LIMITED: (
        SearchRecoveryReason.RATE_LIMITED,
        SearchRecoveryAction.TRY_NEXT_PROVIDER,
    ),
    StandardErrorCode.SEARCH_INVALID_QUERY: (SearchRecoveryReason.INVALID_QUERY, SearchRecoveryAction.STOP),
    StandardErrorCode.CONTENT_PARSE_ERROR: (
        SearchRecoveryReason.PARSER_FAILURE,
        SearchRecoveryAction.TRY_NEXT_PROVIDER,
    ),
    StandardErrorCode.SYSTEM_CONFIG_ERROR: (
        SearchRecoveryReason.CONFIG_ERROR,
        SearchRecoveryAction.TRY_NEXT_PROVIDER,
    ),
    StandardErrorCode.FETCH_CONNECTION_ERROR: (
        SearchRecoveryReason.NETWORK_FAILURE,
        SearchRecoveryAction.TRY_NEXT_PROVIDER,
    ),
    StandardErrorCode.FETCH_DNS_ERROR: (
        SearchRecoveryReason.NETWORK_FAILURE,
        SearchRecoveryAction.TRY_NEXT_PROVIDER,
    ),
    StandardErrorCode.FETCH_SERVER_ERROR: (
        SearchRecoveryReason.SERVER_ERROR,
        SearchRecoveryAction.TRY_NEXT_PROVIDER,
    ),
    StandardErrorCode.FETCH_FORBIDDEN: (SearchRecoveryReason.AUTH_ERROR, SearchRecoveryAction.TRY_NEXT_PROVIDER),
}


@dataclass(frozen=True)
class SearchRecoveryDecision:
    reason: SearchRecoveryReason
    action: SearchRecoveryAction
    details: dict[str, Any] = field(default_factory=dict)


def classify_search_recovery(response: SearchResponse) -> SearchRecoveryDecision:
    """Classify a single provider outcome.

    SUCCESS -> RESULT_AVAILABLE / ACCEPT.
    EMPTY   -> EMPTY_RESULT / TRY_NEXT_PROVIDER.
    ERROR   -> use failure_kind first, then StandardErrorCode, then PROVIDER_ERROR.
    """
    if response.status == SearchStatus.SUCCESS:
        return SearchRecoveryDecision(
            reason=SearchRecoveryReason.RESULT_AVAILABLE,
            action=SearchRecoveryAction.ACCEPT,
            details={"result_count": len(response.results)},
        )
    if response.status == SearchStatus.EMPTY:
        return SearchRecoveryDecision(
            reason=SearchRecoveryReason.EMPTY_RESULT,
            action=SearchRecoveryAction.TRY_NEXT_PROVIDER,
        )

    # ERROR
    if response.failure_kind is not None and response.failure_kind in _KIND_MAP:
        reason, action = _KIND_MAP[response.failure_kind]
        return SearchRecoveryDecision(
            reason=reason, action=action, details={"failure_kind": response.failure_kind.value}
        )

    if response.error_type is not None and response.error_type in _CODE_MAP:
        reason, action = _CODE_MAP[response.error_type]
        return SearchRecoveryDecision(
            reason=reason,
            action=action,
            details={"error_type": response.error_type.value},
        )

    return SearchRecoveryDecision(
        reason=SearchRecoveryReason.PROVIDER_ERROR,
        action=SearchRecoveryAction.TRY_NEXT_PROVIDER,
        details={"error_type": getattr(response.error_type, "value", None)},
    )


def classify_circuit_open() -> SearchRecoveryDecision:
    """A provider skipped because its SearchHealthManager circuit is open."""
    return SearchRecoveryDecision(
        reason=SearchRecoveryReason.CIRCUIT_OPEN,
        action=SearchRecoveryAction.TRY_NEXT_PROVIDER,
    )


def classify_search_final_outcome(
    outcomes: list[SearchRecoveryDecision],
) -> SearchRecoveryDecision:
    """Finalize the whole search route after no provider returned SUCCESS.

    Phase 1 semantics preserved:
      - any EMPTY (even mixed with ERROR) -> ALL_EMPTY / RETURN_EMPTY
      - all hard failures / skipped -> ALL_FAILED / RETURN_ERROR
      - INVALID_QUERY anywhere wins -> STOP (whole request invalid)
    """
    if any(o.reason == SearchRecoveryReason.INVALID_QUERY for o in outcomes):
        return SearchRecoveryDecision(
            reason=SearchRecoveryReason.INVALID_QUERY,
            action=SearchRecoveryAction.STOP,
        )
    if any(o.reason == SearchRecoveryReason.EMPTY_RESULT for o in outcomes):
        return SearchRecoveryDecision(
            reason=SearchRecoveryReason.ALL_EMPTY,
            action=SearchRecoveryAction.RETURN_EMPTY,
        )
    return SearchRecoveryDecision(
        reason=SearchRecoveryReason.ALL_FAILED,
        action=SearchRecoveryAction.RETURN_ERROR,
    )
