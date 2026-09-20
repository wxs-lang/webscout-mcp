"""Deterministic recovery classification (Phase 2.7B).

This module answers two distinct questions about a fast-fetch response:

  Q1. Is the result complete / usable as-is?
  Q2. If not, *why*, and which *category* of recovery action fits?

It ONLY classifies and recommends. It never executes anything: it does not
raise max_chars, continue/chunk content, spawn a browser, retry, fall back to
another provider, or change production routing. Production routing remains
owned by ``fetch_escalation.should_escalate_to_browser`` + ``FetchService``.

The browser-related signals (challenge / JS placeholder / low density / low
quality) are reused from ``fetch_escalation`` — this module does not maintain
a second copy of those markers or thresholds.

Mapping summary (recommendation only):
  OUTPUT_TRUNCATED       -> CONTINUE_CONTENT
  JS_REQUIRED/SOFT_BLOCK/LOW_CONTENT_DENSITY/LOW_QUALITY -> BROWSER
  RATE_LIMITED           -> RETRY_LATER
  AUTH_REQUIRED          -> REQUIRE_AUTH
  LEGAL_OR_GEO_BLOCK     -> STOP
  SERVER_ERROR/TIMEOUT/NETWORK_FAILURE -> RETRY
  TLS_FAILURE            -> PROVIDER_FALLBACK
  ACCESS_DENIED          -> STOP
  UNSUPPORTED_CONTENT_TYPE -> ACCEPT
  COMPLETE_SHORT_PAGE/COMPLETE_CONTENT -> ACCEPT
  AMBIGUOUS              -> NONE
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import StandardErrorCode
from .fetch_escalation import (
    EscalationReason,
    FetchEscalationDecision,
    _looks_like_challenge,
    should_escalate_to_browser,
)
from .fetch_provider import FetchResponse

# Content types that have dedicated parsers — never a browser repair.
_NON_HTML_PREFIXES = (
    "application/pdf",
    "application/json",
    "application/rss",
    "application/xml",
    "text/xml",
    "image/",
)

# A genuinely small rendered page is at most this many extracted chars AND
# must live on a small HTML document (see _complete_short_page).
_SHORT_PAGE_TEXT_CHARS = 2000
# Below this much extracted text on a large script-heavy document we cannot
# confirm completeness even though the strict escalation rule does not fire.
_THIN_SHELL_TEXT_CHARS = 1500
_LARGE_HTML_CHARS = 20_000
_HIGH_SCRIPT_RATIO = 0.15


class RecoveryReason(str, Enum):
    """Why the current result is (or is not) sufficient."""

    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"  # WebScout's own output limit cut content
    JS_REQUIRED = "JS_REQUIRED"
    SOFT_BLOCK = "SOFT_BLOCK"  # 403 challenge / captcha that a browser may pass
    LOW_CONTENT_DENSITY = "LOW_CONTENT_DENSITY"
    LOW_QUALITY = "LOW_QUALITY"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    LEGAL_OR_GEO_BLOCK = "LEGAL_OR_GEO_BLOCK"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    TLS_FAILURE = "TLS_FAILURE"
    TIMEOUT = "TIMEOUT"
    ACCESS_DENIED = "ACCESS_DENIED"  # plain 403/404/robots — browser won't help
    UNSUPPORTED_CONTENT_TYPE = "UNSUPPORTED_CONTENT_TYPE"
    COMPLETE_SHORT_PAGE = "COMPLETE_SHORT_PAGE"
    COMPLETE_CONTENT = "COMPLETE_CONTENT"
    AMBIGUOUS = "AMBIGUOUS"


class RecoveryAction(str, Enum):
    """Recommended recovery action category (never auto-executed here)."""

    ACCEPT = "ACCEPT"
    CONTINUE_CONTENT = "CONTINUE_CONTENT"
    BROWSER = "BROWSER"
    RETRY = "RETRY"
    RETRY_LATER = "RETRY_LATER"
    PROVIDER_FALLBACK = "PROVIDER_FALLBACK"
    REQUIRE_AUTH = "REQUIRE_AUTH"
    STOP = "STOP"
    NONE = "NONE"


_BROWSER_REASONS = {
    EscalationReason.SOFT_BLOCK: RecoveryReason.SOFT_BLOCK,
    EscalationReason.JS_REQUIRED: RecoveryReason.JS_REQUIRED,
    EscalationReason.LOW_CONTENT_DENSITY: RecoveryReason.LOW_CONTENT_DENSITY,
    EscalationReason.LOW_QUALITY: RecoveryReason.LOW_QUALITY,
}


@dataclass
class RecoveryDecision:
    """Classification of a fast-fetch response plus a recommended action."""

    reason: RecoveryReason
    action: RecoveryAction
    confidence: float  # 0..1
    details: dict[str, Any]

    @property
    def recoverable(self) -> bool:
        return self.action not in (RecoveryAction.ACCEPT, RecoveryAction.STOP, RecoveryAction.NONE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason.value,
            "action": self.action.value,
            "confidence": round(self.confidence, 3),
            "recoverable": self.recoverable,
            "details": self.details,
        }


def _d(reason: RecoveryReason, action: RecoveryAction, confidence: float, **details: Any) -> RecoveryDecision:
    return RecoveryDecision(reason=reason, action=action, confidence=confidence, details=details)


def _script_ratio(html: str) -> float:
    import re

    if not html:
        return 0.0
    script_len = sum(
        len(m.group(0)) for m in re.finditer(r"<script\b[^>]*>.*?</script\b[^>]*>", html, re.DOTALL | re.IGNORECASE)
    )
    return script_len / max(len(html), 1)


def _is_non_html(content_type: str) -> bool:
    ctype = (content_type or "").lower()
    return any(ctype.startswith(p) for p in _NON_HTML_PREFIXES)


def classify_recovery(response: FetchResponse) -> RecoveryDecision:
    """Classify a fast-fetch response and recommend (not execute) an action.

    Deterministic priority (first match wins):
      1. legal/geo, auth, rate-limit protocol status
      2. timeout / tls / network / server transport failures
      3. plain access denial (403 without challenge, 404, robots)
      4. non-HTML content types
      5. explicit output-limit truncation
      6. browser signals (soft-block / JS / low density / low quality)
      7. complete short / complete normal / ambiguous
    """
    meta = response.metadata or {}
    status = response.status_code
    details: dict[str, Any] = {"status_code": status}
    error_code = response.error_code
    error_text = (response.error or "").lower()

    # ---- 1. protocol / terminal status -----------------------------------
    if status == 451:
        return _d(RecoveryReason.LEGAL_OR_GEO_BLOCK, RecoveryAction.STOP, 0.95, **details)
    if status in (401, 407):
        return _d(RecoveryReason.AUTH_REQUIRED, RecoveryAction.REQUIRE_AUTH, 0.95, **details)
    if status == 429 or error_code == StandardErrorCode.FETCH_RATE_LIMITED:
        return _d(RecoveryReason.RATE_LIMITED, RecoveryAction.RETRY_LATER, 0.9, **details)

    # ---- 2. transport / server failures ----------------------------------
    if error_code == StandardErrorCode.FETCH_TIMEOUT or "timeout" in error_text or status in (408, 504):
        return _d(RecoveryReason.TIMEOUT, RecoveryAction.RETRY, 0.85, **details)
    if error_code == StandardErrorCode.FETCH_SSL_ERROR or "ssl" in error_text or "certificate" in error_text:
        return _d(RecoveryReason.TLS_FAILURE, RecoveryAction.PROVIDER_FALLBACK, 0.85, **details)
    if (
        error_code in (StandardErrorCode.FETCH_DNS_ERROR, StandardErrorCode.FETCH_CONNECTION_ERROR)
        or "dns" in error_text
        or "connect" in error_text
    ):
        return _d(RecoveryReason.NETWORK_FAILURE, RecoveryAction.RETRY, 0.8, **details)
    if status >= 500 or error_code == StandardErrorCode.FETCH_SERVER_ERROR:
        return _d(RecoveryReason.SERVER_ERROR, RecoveryAction.RETRY, 0.8, **details)

    # ---- 3. access denial -------------------------------------------------
    # 403: only a visible challenge/captcha is a browser candidate. A plain
    # 403 is an access denial — we must not assume a browser fixes every 403.
    if status == 403 or error_code == StandardErrorCode.FETCH_FORBIDDEN:
        raw_html = getattr(response, "raw_html", "") or response.content or ""
        if _looks_like_challenge(raw_html):
            details.update(escalation=EscalationReason.SOFT_BLOCK.value)
            return _d(RecoveryReason.SOFT_BLOCK, RecoveryAction.BROWSER, 0.9, **details)
        return _d(RecoveryReason.ACCESS_DENIED, RecoveryAction.STOP, 0.8, **details)
    if status == 404 or error_code == StandardErrorCode.FETCH_NOT_FOUND:
        return _d(RecoveryReason.ACCESS_DENIED, RecoveryAction.STOP, 0.85, **details)
    if error_code == StandardErrorCode.FETCH_ROBOTS_DENIED or "robots" in error_text:
        return _d(RecoveryReason.ACCESS_DENIED, RecoveryAction.STOP, 0.9, **details)
    # Any other hard error without a more specific class: do not invent one.
    if response.error is not None and not response.is_success:
        if response.retryable:
            return _d(RecoveryReason.NETWORK_FAILURE, RecoveryAction.RETRY, 0.5, **details)
        return _d(RecoveryReason.ACCESS_DENIED, RecoveryAction.STOP, 0.5, **details)

    # ---- 4. non-HTML content uses dedicated parsers ----------------------
    if _is_non_html(response.content_type):
        details["content_type"] = response.content_type
        return _d(RecoveryReason.UNSUPPORTED_CONTENT_TYPE, RecoveryAction.ACCEPT, 0.8, **details)

    # ---- 5. explicit output-limit truncation (real metadata, never guess)
    truncated = bool(meta.get("truncated_by_output_limit", False))
    if truncated:
        details.update(
            pre_limit_content_chars=meta.get("pre_limit_content_chars"),
            returned_content_chars=meta.get("returned_content_chars"),
            output_limit_chars=meta.get("output_limit_chars"),
            omitted_chars=meta.get("omitted_chars"),
        )
        return _d(RecoveryReason.OUTPUT_TRUNCATED, RecoveryAction.CONTINUE_CONTENT, 0.95, **details)

    # ---- 6. browser-related signals (reuse escalation, no duplication) ---
    esc = should_escalate_to_browser(response)
    if esc.escalate and esc.reason_code is not None:
        reason = _BROWSER_REASONS.get(esc.reason_code, RecoveryReason.AMBIGUOUS)
        return _d(
            reason, RecoveryAction.BROWSER, esc.confidence, escalation=esc.reason_code.value, **(esc.details or {})
        )

    # ---- 7. success: decide completeness ---------------------------------
    body = response.content or ""
    if not body.strip():
        # HTTP success but no extractable content and no browser signal —
        # evidence is insufficient, prefer AMBIGUOUS over a false browser call.
        return _d(RecoveryReason.AMBIGUOUS, RecoveryAction.NONE, 0.4, **details)

    raw_html = getattr(response, "raw_html", "") or ""
    script_ratio = _script_ratio(raw_html)
    details.update(text_len=len(body), html_len=len(raw_html), script_ratio=round(script_ratio, 3))

    if len(body) <= _SHORT_PAGE_TEXT_CHARS:
        # A genuine short page is small text on a small document. Short text
        # sitting on a large script-heavy shell is not provably complete.
        thin_shell = (
            len(body) < _THIN_SHELL_TEXT_CHARS
            and len(raw_html) > _LARGE_HTML_CHARS
            and script_ratio > _HIGH_SCRIPT_RATIO
        )
        if thin_shell:
            return _d(RecoveryReason.AMBIGUOUS, RecoveryAction.NONE, 0.45, **details)
        return _d(RecoveryReason.COMPLETE_SHORT_PAGE, RecoveryAction.ACCEPT, 0.8, **details)

    return _d(RecoveryReason.COMPLETE_CONTENT, RecoveryAction.ACCEPT, 0.85, **details)


# RecoveryReason -> legacy browser EscalationReason, for the compatibility
# adapter. Only browser-class reasons map back.
_REASON_TO_LEGACY_ESCALATION = {
    RecoveryReason.SOFT_BLOCK: EscalationReason.SOFT_BLOCK,
    RecoveryReason.JS_REQUIRED: EscalationReason.JS_REQUIRED,
    RecoveryReason.LOW_CONTENT_DENSITY: EscalationReason.LOW_CONTENT_DENSITY,
    RecoveryReason.LOW_QUALITY: EscalationReason.LOW_QUALITY,
}


def recovery_to_legacy_escalation(decision: RecoveryDecision) -> FetchEscalationDecision | None:
    """Compatibility adapter (Phase 2.7D).

    Derive the legacy ``FetchEscalationDecision`` from the single
    ``RecoveryDecision`` so FetchService never runs the low-level browser
    detector a second time. Returns None for every non-browser action.
    """
    if decision.action is not RecoveryAction.BROWSER:
        return None
    # Prefer the escalation code the classifier already captured in details.
    code = decision.details.get("escalation") if decision.details else None
    reason: EscalationReason | None = None
    if code:
        try:
            reason = EscalationReason(code)
        except ValueError:
            reason = _REASON_TO_LEGACY_ESCALATION.get(decision.reason)
    else:
        reason = _REASON_TO_LEGACY_ESCALATION.get(decision.reason)
    if reason is None:
        return None
    # Only safe scalar details cross the compatibility boundary.
    safe_details = {k: v for k, v in (decision.details or {}).items() if isinstance(v, (str, int, float, bool))}
    return FetchEscalationDecision(
        escalate=True,
        reason_code=reason,
        confidence=decision.confidence,
        details=safe_details,
    )
