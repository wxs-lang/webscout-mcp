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

from .core.errors import StandardErrorCode
from .fetch_escalation import (
    _MIN_HTML_BYTES_FOR_LOW_DENSITY,
    _NON_HTML_PREFIXES,
    EscalationReason,
    FetchEscalationDecision,
    _looks_like_challenge,
    should_escalate_to_browser,
)
from .fetch_provider import FetchResponse

# Content types that have dedicated parsers — never a browser repair.
# Imported from fetch_escalation rather than redeclared: this module's docstring
# already promises not to keep a second copy of those markers, and a duplicate
# tuple could drift with nothing to notice. Kept importable from here because
# existing callers and tests reference recovery._NON_HTML_PREFIXES.

# A genuinely small rendered page is at most this many extracted chars AND
# must live on a small HTML document (see _complete_short_page).
_SHORT_PAGE_TEXT_CHARS = 2000
# Below this much extracted text on a large script-heavy document we cannot
# confirm completeness even though the strict escalation rule does not fire.
_THIN_SHELL_TEXT_CHARS = 1500
_LARGE_HTML_CHARS = 20_000
_HIGH_SCRIPT_RATIO = 0.15

# A large page whose extraction kept almost none of it did not extract - it failed.
#
# Measured across seven reachable sites, body/raw ratio:
#   medium 0.0026 (134 chars from 52 KB - content discarded),
#   mozilla 0.0132 (thin but usable), wikipedia 0.0684, docs.python 0.2488.
# 0.005 sits below every working site and above the broken one.
#
# Needed because script_ratio measures script *bytes*: medium's 52 KB is mostly markup and
# style, so 17 <script> tags still left the ratio under the thin_shell threshold.
_EXTRACTION_COLLAPSE_RATIO = 0.005
_EXTRACTION_COLLAPSE_MIN_HTML = 20_000

# A 403 that returned at least this many bytes of HTML body is treated as a
# UA-level soft block (the server rejected our client fingerprint but serves
# real markup to a real browser). Below this, there is no evidence a browser
# would help, so we stay conservative.
_MIN_403_HTML_BYTES = 256

# Strong login-wall markers. A 403 page that explicitly demands
# authentication is NOT a browser-recoverable soft block: a browser cannot
# bypass a real login requirement, so we must not escalate into it.
# How much of a document to search for login vocabulary.
#
# 48 KB, not the 8 KB this used to use. Measured on zhihu.com: every login marker sits at
# offset 12.5-18.5 KB in a 45 KB document, because inline CSS and the script bootstrap push
# the real UI markup well past 8 KB. An 8 KB slice therefore returned False for an
# unambiguous wall, and the page went on to be graded `usable` and escalated to a browser.
#
# Bounded rather than whole-document: this runs on every response, and a page that has
# rendered its UI has done so within this slice.
LOGIN_WALL_SCAN_CHARS = 48_000

_LOGIN_WALL_MARKERS = (
    "please log in",
    "please sign in",
    "log in to view",
    "sign in to view",
    "login required",
    "sign in required",
    "must be logged in",
    "please login",
    "需要登录",
    "请登录",
    "登录后查看",
    "登录后才能",
    "请先登录",
    # Login *forms* rather than login *demands*. The markers above catch a page telling you
    # to sign in; these catch one showing you the controls. Measured: zhihu.com serves a
    # login page using this vocabulary and matched none of the markers above.
    "验证码登录",
    "登录/注册",
    "忘记密码",
    "获取短信验证码",
    "自动登录",
    "login / register",
    "forgot password",
    "send code",
)


class RecoveryReason(str, Enum):
    """Why the current result is (or is not) sufficient."""

    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"  # WebScout's own output limit cut content
    JS_REQUIRED = "JS_REQUIRED"
    SOFT_BLOCK = "SOFT_BLOCK"
    # An explicit interstitial telling the visitor to wait for a check. Distinct
    # from SOFT_BLOCK ("server rejected our fingerprint") because the page says
    # what it is, and a caller can act on that difference.
    CHALLENGE = "CHALLENGE"  # 403 challenge / captcha that a browser may pass
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
    EscalationReason.CHALLENGE: RecoveryReason.CHALLENGE,
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


def _looks_like_login_wall(html: str) -> bool:
    """Detect an explicit authentication wall in a 403 body.

    A page that explicitly demands login is not browser-recoverable (a real
    browser cannot bypass credentials), so escalation must be suppressed.
    Only strong phrases are matched to avoid false positives on pages that
    merely link to a login page in their navigation.
    """
    head = (html or "")[:LOGIN_WALL_SCAN_CHARS].lower()
    return any(m in head for m in _LOGIN_WALL_MARKERS)


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

    # 202 means "accepted for processing, not completed", so it cannot be COMPLETE_CONTENT
    # by default. Measured on amazon.com: a 202 carried "JavaScript is disabled ... verify
    # that you're not a robot" and fell through to COMPLETE_CONTENT, reporting
    # `error=None, outcome=accepted` for a bot challenge. v1.14.0 fixed that shape for a
    # 200; 202 had no branch and slipped past the same way.
    #
    # Judged by content rather than by status: a site that genuinely answers 202 with real
    # content is still a success. Anything else is not usable, so a browser escalation is
    # the appropriate next step - same action a soft block gets.
    if status == 202:
        body = response.content or ""
        try:
            from .content_grading import assess

            grade = assess(body).grade
        except Exception:  # pragma: no cover - grading must never break classification
            # No logger in this module, and a grading failure must not change the decision:
            # falling back to "usable" preserves the pre-fix behaviour for that case only.
            grade = "usable"
        details["content_grade"] = grade
        if grade == "usable":
            return _d(RecoveryReason.COMPLETE_CONTENT, RecoveryAction.ACCEPT, 0.8, **details)
        details.update(escalation=EscalationReason.SOFT_BLOCK.value)
        return _d(RecoveryReason.SOFT_BLOCK, RecoveryAction.BROWSER, 0.85, **details)

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
    # 403 has three distinct classes:
    #   (a) a visible challenge/captcha -> strong browser candidate;
    #   (b) a non-empty HTML body that is NOT a challenge and NOT a login
    #       wall -> UA-level soft block: the server rejected our client
    #       fingerprint but serves real markup to a real browser, so a
    #       single bounded browser escalation is appropriate;
    #   (c) empty/tiny body, login wall, or non-HTML payload -> genuine
    #       access denial, a browser will not help, do not escalate.
    if status == 403 or error_code == StandardErrorCode.FETCH_FORBIDDEN:
        raw_html = getattr(response, "raw_html", "") or response.content or ""
        if _looks_like_challenge(raw_html):
            details.update(escalation=EscalationReason.SOFT_BLOCK.value)
            return _d(RecoveryReason.SOFT_BLOCK, RecoveryAction.BROWSER, 0.9, **details)
        if _is_non_html(response.content_type):
            details["content_type"] = response.content_type
            return _d(RecoveryReason.ACCESS_DENIED, RecoveryAction.STOP, 0.8, **details)
        if _looks_like_login_wall(raw_html):
            details.update(escalation="LOGIN_WALL")
            return _d(RecoveryReason.ACCESS_DENIED, RecoveryAction.STOP, 0.85, **details)
        if len(raw_html.strip()) >= _MIN_403_HTML_BYTES:
            details.update(escalation=EscalationReason.SOFT_BLOCK.value, body_chars=len(raw_html))
            return _d(RecoveryReason.SOFT_BLOCK, RecoveryAction.BROWSER, 0.7, **details)
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

    # ---- 4b. an HTML body we could not extract is not article text ------
    # Every length-based judgement below becomes wrong when the "content" is
    # really the page source: a truncated HTML body looks like a truncated
    # article (step 5) and a 2KB bot-check page looks complete (step 7). Detect
    # the shape once, here, and route it through the browser signals in step 6.
    _ctype = (getattr(response, "content_type", "") or "").lower()
    _raw_html = getattr(response, "raw_html", "") or ""
    # The signal is that CONTENT is markup, not that raw_html exists - raw_html
    # always exists for HTML pages, including ones we extracted successfully.
    # When extraction works, content is markdown and raw_html holds the source;
    # when it fails, content still holds the source.
    _head = (response.content or "")[:2000].lower()
    _content_is_markup = "<html" in _head or "<!doctype" in _head
    _extraction_status = getattr(response, "extraction_status", None)
    # "unavailable" means no extractor is installed. Rendering the page in a
    # browser would return markup that the same missing extractor cannot read, so
    # escalating only costs seconds. Only "empty" - an extractor ran and found
    # nothing - is worth a browser attempt.
    _extraction_could_improve = _extraction_status != "unavailable"
    unextracted_html = (
        "html" in _ctype
        and not bool(getattr(response, "extracted", False))
        and _content_is_markup
        and _extraction_could_improve
    )
    if unextracted_html:
        details.update(
            text_len=len(response.content or ""),
            html_len=len(_raw_html),
            extraction_status=_extraction_status,
        )

    # ---- 5. explicit output-limit truncation (real metadata, never guess)
    truncated = bool(meta.get("truncated_by_output_limit", False))
    if truncated and not unextracted_html:
        details.update(
            pre_limit_content_chars=meta.get("pre_limit_content_chars"),
            returned_content_chars=meta.get("returned_content_chars"),
            output_limit_chars=meta.get("output_limit_chars"),
            omitted_chars=meta.get("omitted_chars"),
        )
        return _d(RecoveryReason.OUTPUT_TRUNCATED, RecoveryAction.CONTINUE_CONTENT, 0.95, **details)

    # ---- 5b. login wall on any successful status -------------------------
    # A login wall is not browser-recoverable: rendition cannot supply credentials. This
    # was checked only inside the 403 branch, which encoded "a login wall is a 403" as an
    # assumption. Measured on zhihu.com: a 200 carrying a login page skipped the check
    # entirely, was graded `usable` because the UI text reads as prose, and then spent a
    # browser launch on a page no browser can get past.
    #
    # Before the browser-signal step so it pre-empts escalation rather than competing.
    if status < 400:
        raw_body = getattr(response, "raw_html", "") or response.content or ""
        if _looks_like_login_wall(raw_body):
            details.update(escalation="LOGIN_WALL")
            return _d(RecoveryReason.AUTH_REQUIRED, RecoveryAction.REQUIRE_AUTH, 0.85, **details)

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

    if unextracted_html:
        # Small unextracted documents cannot be JS shells: a sub-3KB HTML
        # file (the same threshold should_escalate_to_browser uses to define
        # "big enough to be a SPA shell") carries no script payload worth
        # rendering. The fetch already holds the COMPLETE page — every byte
        # of it — and a chromium launch would re-download those same bytes
        # and re-run the same failing extraction. Measured 2026-11-14:
        # example.org (577B) paid a full playwright launch per call because
        # trafilatura rejects barebones pages 29/30 times, purely by
        # heuristic; the browser returned the identical 577 bytes. Accept
        # the raw markup as the complete short page instead: the agent can
        # read small HTML directly, and the fetch was a 200 with the whole
        # document in hand. Larger documents keep the browser escalation —
        # a 3000B+ shell with empty extraction IS the JS-rendered case.
        if len(response.content or "") < _MIN_HTML_BYTES_FOR_LOW_DENSITY:
            details.update(
                text_len=len(response.content or ""),
                html_len=len(_raw_html),
                extraction_status=_extraction_status,
                note=(
                    "page is a complete small document; extraction found no article "
                    "text, serving the raw markup — a browser render would return "
                    "the same bytes"
                ),
            )
            return _d(RecoveryReason.COMPLETE_SHORT_PAGE, RecoveryAction.ACCEPT, 0.8, **details)
        # The body exists but is markup, not text: we downloaded the page and
        # could not read it. That is the content-poor case B2 describes, not a
        # complete short page and not a longer article to continue into.
        return _d(RecoveryReason.LOW_CONTENT_DENSITY, RecoveryAction.BROWSER, 0.7, **details)

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

        # A big page that yielded almost no text did not extract. Measured: medium.com's
        # 52 KB produced a 134-char nav bar and was accepted as a complete short page, so a
        # caller could not tell it from a genuinely nav-only page.
        collapsed = (
            len(raw_html) >= _EXTRACTION_COLLAPSE_MIN_HTML
            and (len(body) / max(len(raw_html), 1)) < _EXTRACTION_COLLAPSE_RATIO
        )
        if collapsed:
            details["body_to_raw_ratio"] = round(len(body) / max(len(raw_html), 1), 5)
            return _d(RecoveryReason.AMBIGUOUS, RecoveryAction.BROWSER, 0.6, **details)

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
