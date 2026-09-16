"""Decide whether a plain HTTP fetch should be escalated to a browser backend.

This module is the single source of truth for "the fast fetch did not do a
good enough job, ask Crawl4AI to render it". It intentionally does NOT call
any browser backend itself — it only inspects the FetchResponse that the
fast HTTP fetch produced and returns a structured decision.

Rules (locked in v1.2.2):
  escalate on:
    - HTTP 403                                              (SOFT_BLOCK)
    - HTTP 200 + Cloudflare/challenge/captcha markers       (SOFT_BLOCK)
    - HTTP 200 + "Enable JavaScript" / JS-only placeholders (JS_REQUIRED)
    - extracted text very short AND html/script heavy       (LOW_CONTENT_DENSITY)
    - content_quality == low AND page size non-trivial      (LOW_QUALITY)
  never escalate on:
    - HTTP 451 (legal/geo block — browser won't help)
    - HTTP 429 (rate limit — back off, don't add pressure)
    - HTTP 401/407 (auth — not a rendering problem)
    - DNS / TLS / connect failures (browser can't fix)
    - PDF / JSON / RSS / images (use their own parsers)
    - 5xx (retry, don't spawn Chromium)

The decision object is also the unit of measurement: future versions can
count how often each reason_code fired and whether the browser backend
actually recovered the content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .fetch_provider import FetchResponse


class EscalationReason(str, Enum):
    SOFT_BLOCK = "SOFT_BLOCK"  # 403 / challenge / captcha
    JS_REQUIRED = "JS_REQUIRED"  # explicit "enable JavaScript" placeholder
    LOW_CONTENT_DENSITY = "LOW_CONTENT_DENSITY"  # short text + heavy HTML/scripts
    LOW_QUALITY = "LOW_QUALITY"  # analyzer marked the extracted content low quality


# Markers that almost always mean a real browser is required.
_CHALLENGE_MARKERS = (
    "cloudflare",
    "attention required",
    "checking your browser",
    "just a moment",
    "captcha",
    "are you a human",
    "cf-browser-verification",
    "challenge-platform",
)

_JS_PLACEHOLDER_MARKERS = (
    "enable javascript",
    "javascript is required",
    "please enable javascript",
    "you need to enable javascript",
    "<noscript>",
)

# Content types that have their own parsers and should never go to a browser.
_NON_HTML_PREFIXES = (
    "application/pdf",
    "application/json",
    "application/rss",
    "application/xml",
    "text/xml",
    "image/",
)

# Thresholds. Tuned conservatively so we only escalate when we are fairly
# confident the fast fetch missed the real content.
_MIN_HTML_BYTES_FOR_LOW_DENSITY = 3000
_MIN_TEXT_CHARS_FOR_REAL_PAGE = 200
_MIN_PAGE_BYTES_FOR_LOW_QUALITY = 2000


@dataclass
class FetchEscalationDecision:
    """Structured decision returned by :func:`should_escalate_to_browser`."""

    escalate: bool
    reason_code: EscalationReason | None = None
    confidence: float = 0.0  # 0..1; 1 = "we are sure browser helps"
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalate": self.escalate,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "confidence": round(self.confidence, 3),
            "details": self.details or {},
        }


def _looks_like_challenge(html: str) -> bool:
    head = html[:4096].lower()
    return any(m in head for m in _CHALLENGE_MARKERS)


def _looks_like_js_placeholder(html: str) -> bool:
    head = html[:4096].lower()
    # A real page with a tiny <noscript> fallback is fine; we only escalate
    # when the whole page body is basically "enable JS".
    if any(m in head for m in _JS_PLACEHOLDER_MARKERS[:-1]):
        return True
    # <noscript> present and the extracted text is essentially empty.
    return False


def _script_ratio(html: str) -> float:
    if not html:
        return 0.0
    script_len = sum(len(m.group(0)) for m in re.finditer(r"<script[^>]*>.*?</script>", html, re.DOTALL | re.IGNORECASE))
    return script_len / max(len(html), 1)


def should_escalate_to_browser(response: FetchResponse) -> FetchEscalationDecision:
    """Inspect a fast-fetch response and decide whether to escalate.

    Args:
        response: The FetchResponse produced by the plain HTTP fetcher.

    Returns:
        A FetchEscalationDecision. ``escalate=False`` is the safe default;
        callers must respect it and NOT call the browser backend.
    """
    details: dict[str, Any] = {"status_code": response.status_code}
    meta = response.metadata or {}

    # --- Hard "do not escalate" cases -------------------------------------
    if response.status_code in (451, 429, 401, 407):
        return FetchEscalationDecision(False, details=details)

    if response.error is not None:
        low = response.error.lower()
        if any(k in low for k in ("dns", "ssl", "certificate", "connect", "timeout", "robot")):
            return FetchEscalationDecision(False, details=details)
        # 5xx: retry, don't spawn Chromium.
        if response.status_code >= 500:
            return FetchEscalationDecision(False, details=details)

    ctype = (response.content_type or "").lower()
    if any(ctype.startswith(p) for p in _NON_HTML_PREFIXES):
        details["content_type"] = ctype
        return FetchEscalationDecision(False, details=details)

    # --- Hard "escalate" cases --------------------------------------------
    if response.status_code == 403:
        details["content_type"] = ctype
        return FetchEscalationDecision(
            escalate=True,
            reason_code=EscalationReason.SOFT_BLOCK,
            confidence=0.9,
            details=details,
        )

    # On success, inspect the body we got.
    body = response.content or ""
    raw_html = meta.get("raw_html", "") or body
    details["text_len"] = len(body)
    details["html_len"] = len(raw_html)
    details["script_ratio"] = round(_script_ratio(raw_html), 3)

    if response.status_code == 200:
        if _looks_like_challenge(raw_html):
            return FetchEscalationDecision(
                escalate=True,
                reason_code=EscalationReason.SOFT_BLOCK,
                confidence=0.95,
                details=details,
            )
        if _looks_like_js_placeholder(raw_html):
            return FetchEscalationDecision(
                escalate=True,
                reason_code=EscalationReason.JS_REQUIRED,
                confidence=0.85,
                details=details,
            )

        # Low content density: very little extracted text, but the HTML is
        # non-trivial. This is the classic "JS-rendered SPA" signature.
        if (
            len(body) < _MIN_TEXT_CHARS_FOR_REAL_PAGE
            and len(raw_html) > _MIN_HTML_BYTES_FOR_LOW_DENSITY
        ):
            sr = _script_ratio(raw_html)
            if sr > 0.2 or _looks_like_js_placeholder(raw_html):
                return FetchEscalationDecision(
                    escalate=True,
                    reason_code=EscalationReason.LOW_CONTENT_DENSITY,
                    confidence=0.8,
                    details=details,
                )

        # Content-quality analyzer (if the fetcher ran it) flagged the page.
        if meta.get("content_quality") == "low" and len(raw_html) > _MIN_PAGE_BYTES_FOR_LOW_QUALITY:
            return FetchEscalationDecision(
                escalate=True,
                reason_code=EscalationReason.LOW_QUALITY,
                confidence=0.6,
                details=details,
            )

    return FetchEscalationDecision(False, details=details)
