"""Single, inspectable source of truth for fetch recovery policy.

Why this module exists
----------------------
Recovery policy is currently spread across two modules and many local
constants: ``recovery.classify_recovery`` runs a 7-stage priority chain,
``fetch_escalation.should_escalate_to_browser`` runs a second, overlapping
detector, and the thresholds they use live as private module-level names.
Nothing exposes the policy as data, so the only way to answer "why did this
request escalate?" is to read both files and reconstruct the ordering by hand.

That is the gap this module closes. It declares the policy as plain data —
thresholds, marker sets, the reason→action table, and the ordered stages — so
that:

  * the policy can be printed, diffed and reviewed as a table;
  * duplicated constants have exactly one definition;
  * a change to a threshold is a visible one-line edit, not a hunt.

Deliberately read-only
----------------------
Nothing here executes or changes recovery behaviour. ``classify_recovery`` and
``should_escalate_to_browser`` keep their current logic and remain the code
that actually decides. This module describes what they do. Consumers may import
it for reporting and for drift tests that assert the two agree; rewiring the
classifiers to *read* these values is a separate, riskier change.

The distinction matters. Making the policy inspectable cannot change a verdict,
so it can ship on its own and be verified by comparing its report against the
existing behaviour. Making the classifiers consume it could change a verdict,
and should be judged by the A/B harness.

Terminology
-----------
"Stage" = one step in ``classify_recovery``'s first-match-wins chain. "Signal"
= one browser-escalation rule in ``should_escalate_to_browser``. They overlap
but are not the same thing: several stages never escalate, and the browser
detector re-examines some conditions already covered by recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .fetch_escalation import EscalationReason
from .recovery import RecoveryAction, RecoveryReason

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
# These mirror the private constants in recovery.py and fetch_escalation.py.
# tests/test_policy_table.py asserts they stay equal; if one drifts the test
# fails rather than the documentation quietly lying.


@dataclass(frozen=True)
class Threshold:
    """A numeric policy threshold, with the reasoning that justifies it."""

    name: str
    value: float
    unit: str
    rationale: str
    module: str
    """Which module currently owns the live value."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "rationale": self.rationale,
            "module": self.module,
        }


THRESHOLDS: tuple[Threshold, ...] = (
    Threshold(
        name="SHORT_PAGE_TEXT_CHARS",
        value=2000,
        unit="chars",
        rationale=(
            "A genuinely small rendered page is at most this many extracted chars AND must "
            "sit on a small HTML document. Both conditions are needed; short text on a large "
            "document is a JS shell, not a short page."
        ),
        module="recovery",
    ),
    Threshold(
        name="THIN_SHELL_TEXT_CHARS",
        value=1500,
        unit="chars",
        rationale=(
            "Below this much extracted text on a script-heavy document, completeness cannot be "
            "confirmed even though the strict escalation rule did not fire."
        ),
        module="recovery",
    ),
    Threshold(
        name="LARGE_HTML_CHARS",
        value=20000,
        unit="chars",
        rationale="HTML above this size counts as a 'large document' for the shell test.",
        module="recovery",
    ),
    Threshold(
        name="HIGH_SCRIPT_RATIO",
        value=0.15,
        unit="ratio",
        rationale="Script bytes / total bytes above this means the page is mostly code, not prose.",
        module="recovery",
    ),
    Threshold(
        name="MIN_403_HTML_BYTES",
        value=256,
        unit="bytes",
        rationale=(
            "A 403 with at least this much HTML body is treated as a UA-level soft block: the "
            "server rejected our client fingerprint but serves real markup to a browser. Below "
            "it there is no evidence a browser would help, so we stay conservative."
        ),
        module="recovery",
    ),
    Threshold(
        name="MIN_TEXT_CHARS_FOR_REAL_PAGE",
        value=200,
        unit="chars",
        rationale="Extracted text below this on a non-trivial document is an empty-shell signature.",
        module="fetch_escalation",
    ),
    Threshold(
        name="MIN_HTML_BYTES_FOR_LOW_DENSITY",
        value=3000,
        unit="bytes",
        rationale=(
            "Low-density escalation requires a non-trivial document. Below this size a page is "
            "simply small, and escalating would burn a browser call for nothing."
        ),
        module="fetch_escalation",
    ),
    Threshold(
        name="MIN_PAGE_BYTES_FOR_LOW_QUALITY",
        value=2000,
        unit="bytes",
        rationale="The content-quality signal only counts on documents big enough to judge.",
        module="fetch_escalation",
    ),
    Threshold(
        name="LOW_DENSITY_SCRIPT_RATIO",
        value=0.2,
        unit="ratio",
        rationale=(
            "Script ratio that marks an SPA shell inside the low-density rule. NOTE: this is "
            "currently hardcoded as a literal in fetch_escalation (sr > 0.2) and is stricter "
            "than HIGH_SCRIPT_RATIO (0.15) used by recovery. The divergence is real, not a typo, "
            "and is recorded here so it is visible rather than buried."
        ),
        module="fetch_escalation",
    ),
)


# ---------------------------------------------------------------------------
# Marker sets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkerSet:
    """A set of substring markers used by a policy rule."""

    name: str
    markers: tuple[str, ...]
    purpose: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "count": len(self.markers),
            "markers": list(self.markers),
            "purpose": self.purpose,
        }


MARKER_SETS: tuple[MarkerSet, ...] = (
    MarkerSet(
        name="CHALLENGE_MARKERS",
        markers=(
            "cloudflare",
            "attention required",
            "checking your browser",
            "just a moment",
            "captcha",
            "are you a human",
            "cf-browser-verification",
            "challenge-platform",
        ),
        purpose="Detect an interstitial challenge page where a browser could plausibly pass.",
    ),
    MarkerSet(
        name="JS_PLACEHOLDER_MARKERS",
        markers=(
            "enable javascript",
            "javascript is required",
            "please enable javascript",
            "you need to enable javascript",
            "<noscript>",
        ),
        purpose="Detect a page that renders nothing without client-side JS.",
    ),
    MarkerSet(
        name="LOGIN_WALL_MARKERS",
        markers=(
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
        ),
        purpose=(
            "Detect a genuine authentication requirement. A browser cannot bypass a real login, "
            "so this must NOT escalate - escalating here wastes a browser call and still fails. "
            "Includes Chinese markers because the target sites are not all English."
        ),
    ),
    MarkerSet(
        name="NON_HTML_PREFIXES",
        markers=(
            "application/pdf",
            "application/json",
            "application/rss",
            "application/xml",
            "text/xml",
            "image/",
        ),
        purpose=(
            "Content types that dedicated parsers handle. Escalating to a browser for these "
            "would be wrong. NOTE: this tuple is currently defined twice - once in recovery and "
            "once in fetch_escalation."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Reason -> action
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReasonRule:
    """What a classification reason means and what action it drives."""

    reason: str
    action: str
    confidence: float
    rationale: str
    escalates: bool
    """True when this reason leads to a browser escalation."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "action": self.action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "escalates": self.escalates,
        }


REASON_RULES: tuple[ReasonRule, ...] = (
    ReasonRule(
        "LEGAL_OR_GEO_BLOCK",
        "STOP",
        0.95,
        "HTTP 451: legally unavailable in this jurisdiction. No client-side action can change it.",
        False,
    ),
    ReasonRule(
        "AUTH_REQUIRED",
        "REQUIRE_AUTH",
        0.95,
        "HTTP 401/407: the caller must supply credentials. Escalating would only reach the same wall.",
        False,
    ),
    ReasonRule(
        "RATE_LIMITED",
        "RETRY_LATER",
        0.90,
        "HTTP 429: the host asked us to back off. Retrying immediately makes it worse.",
        False,
    ),
    ReasonRule(
        "TIMEOUT",
        "RETRY",
        0.85,
        "Transport timeout. The Fetcher already exhausted its own retries before classification.",
        False,
    ),
    ReasonRule(
        "TLS_FAILURE",
        "PROVIDER_FALLBACK",
        0.85,
        "Certificate/TLS failure: a different provider may have a working trust path.",
        False,
    ),
    ReasonRule(
        "NETWORK_FAILURE",
        "RETRY",
        0.80,
        "DNS or connection failure: transient by nature, worth one more attempt.",
        False,
    ),
    ReasonRule(
        "SERVER_ERROR",
        "RETRY",
        0.80,
        "HTTP 5xx: the origin is unhealthy, not our request.",
        False,
    ),
    ReasonRule(
        "SOFT_BLOCK",
        "BROWSER",
        # Confidence varies by trigger (0.9 challenge, 0.7 large body, 0.95 in escalation).
        # Recorded here as the representative value; the exact number is set in code.
        0.90,
        (
            "A challenge/captcha page, or a 403 serving real markup to browsers while rejecting "
            "our client fingerprint. This is the case a browser can actually fix."
        ),
        True,
    ),
    ReasonRule(
        "ACCESS_DENIED",
        "STOP",
        0.85,
        (
            "403 with no challenge, 404, robots denial, or a login wall. A browser would hit the "
            "same denial; escalating is pure cost."
        ),
        False,
    ),
    ReasonRule(
        "UNSUPPORTED_CONTENT_TYPE",
        "ACCEPT",
        0.80,
        "Non-HTML payload (PDF/JSON/XML/image): a dedicated parser handles it, a browser cannot.",
        False,
    ),
    ReasonRule(
        "OUTPUT_TRUNCATED",
        "CONTINUE_CONTENT",
        0.95,
        (
            "WebScout's own max_chars cut a larger body. The content exists and is already "
            "fetched; the fix is to serve the next window, never to open Chromium."
        ),
        False,
    ),
    ReasonRule(
        "JS_REQUIRED",
        "BROWSER",
        0.85,
        "Page renders nothing without client-side JS, so a real browser is the only way in.",
        True,
    ),
    ReasonRule(
        "LOW_CONTENT_DENSITY",
        "BROWSER",
        0.80,
        "Classic SPA shell: very little text on a non-trivial, script-heavy document.",
        True,
    ),
    ReasonRule(
        "LOW_QUALITY",
        "BROWSER",
        0.60,
        (
            "The content-quality analyzer flagged the page. Lowest confidence of the browser "
            "reasons, because the analyzer is a heuristic over already-extracted text."
        ),
        True,
    ),
    ReasonRule(
        "AMBIGUOUS",
        "NONE",
        0.40,
        (
            "HTTP success, no extractable content, no browser signal. Evidence is insufficient, "
            "so we prefer a non-answer over a speculative browser call."
        ),
        False,
    ),
    ReasonRule(
        "COMPLETE_SHORT_PAGE",
        "ACCEPT",
        0.70,
        "Genuinely short page: small text on a small document. Nothing more to get.",
        False,
    ),
    ReasonRule(
        "COMPLETE_CONTENT",
        "ACCEPT",
        0.90,
        "Content is present and dense enough. Accept as-is.",
        False,
    ),
)


# ---------------------------------------------------------------------------
# Ordered stages
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    """One step of classify_recovery's first-match-wins chain."""

    order: int
    name: str
    condition: str
    yields: tuple[str, ...]
    """Reasons this stage can produce."""

    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "name": self.name,
            "condition": self.condition,
            "yields": list(self.yields),
            "note": self.note,
        }


CLASSIFY_STAGES: tuple[Stage, ...] = (
    Stage(
        1,
        "protocol_terminal_status",
        "HTTP 451 / 401 / 407 / 429",
        ("LEGAL_OR_GEO_BLOCK", "AUTH_REQUIRED", "RATE_LIMITED"),
        "Checked before anything else: these are final answers, not fetch problems.",
    ),
    Stage(
        2,
        "transport_failure",
        "timeout / TLS / DNS / connection / HTTP 5xx",
        ("TIMEOUT", "TLS_FAILURE", "NETWORK_FAILURE", "SERVER_ERROR"),
    ),
    Stage(
        3,
        "access_denial",
        "403 (three sub-cases), 404, robots, other hard errors",
        ("SOFT_BLOCK", "ACCESS_DENIED"),
        (
            "403 splits three ways: challenge -> BROWSER; real markup above "
            "MIN_403_HTML_BYTES -> SOFT_BLOCK/BROWSER at 0.7; login wall or empty -> "
            "ACCESS_DENIED/STOP. Order matters: the login-wall check must precede the "
            "body-size check, or a large login page would be mistaken for a soft block."
        ),
    ),
    Stage(
        4,
        "non_html_content",
        "content type in NON_HTML_PREFIXES",
        ("UNSUPPORTED_CONTENT_TYPE",),
    ),
    Stage(
        5,
        "output_truncation",
        "metadata.truncated_by_output_limit",
        ("OUTPUT_TRUNCATED",),
        "Uses real metadata only. Never inferred, never guessed from content length.",
    ),
    Stage(
        6,
        "browser_signal",
        "should_escalate_to_browser() returns escalate=True",
        ("SOFT_BLOCK", "JS_REQUIRED", "LOW_CONTENT_DENSITY", "LOW_QUALITY"),
        "Delegates to fetch_escalation rather than duplicating its markers.",
    ),
    Stage(
        7,
        "success_completeness",
        "body empty / short / dense",
        ("AMBIGUOUS", "COMPLETE_SHORT_PAGE", "COMPLETE_CONTENT"),
        "Empty body yields AMBIGUOUS, not a browser call: insufficient evidence.",
    ),
)


# ---------------------------------------------------------------------------
# Browser escalation signals
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EscalationSignal:
    """One rule inside should_escalate_to_browser."""

    name: str
    condition: str
    reason: str
    confidence: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "condition": self.condition,
            "reason": self.reason,
            "confidence": self.confidence,
            "note": self.note,
        }


ESCALATION_SIGNALS: tuple[EscalationSignal, ...] = (
    EscalationSignal(
        "non_html",
        "content type in NON_HTML_PREFIXES",
        "NOT_ESCALATED",
        0.0,
        "Explicitly suppressed: dedicated parsers handle these.",
    ),
    EscalationSignal(
        "challenge_on_any_status",
        "CHALLENGE_MARKERS present",
        "SOFT_BLOCK",
        0.90,
        "Checked before status branching: a challenge page can arrive with non-200 too.",
    ),
    EscalationSignal(
        "challenge_on_200",
        "CHALLENGE_MARKERS present in a 200 body",
        "SOFT_BLOCK",
        0.95,
    ),
    EscalationSignal(
        "js_placeholder_on_200",
        "JS_PLACEHOLDER_MARKERS present in a 200 body",
        "JS_REQUIRED",
        0.85,
    ),
    EscalationSignal(
        "low_density",
        "text < MIN_TEXT_CHARS_FOR_REAL_PAGE AND html > MIN_HTML_BYTES_FOR_LOW_DENSITY "
        "AND (script_ratio > LOW_DENSITY_SCRIPT_RATIO OR js placeholder)",
        "LOW_CONTENT_DENSITY",
        0.80,
    ),
    EscalationSignal(
        "low_quality",
        "metadata.content_quality == 'low' AND html > MIN_PAGE_BYTES_FOR_LOW_QUALITY",
        "LOW_QUALITY",
        0.60,
    ),
)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


@dataclass
class PolicyTable:
    thresholds: tuple[Threshold, ...] = THRESHOLDS
    markers: tuple[MarkerSet, ...] = MARKER_SETS
    reasons: tuple[ReasonRule, ...] = REASON_RULES
    stages: tuple[Stage, ...] = CLASSIFY_STAGES
    signals: tuple[EscalationSignal, ...] = ESCALATION_SIGNALS
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thresholds": [t.to_dict() for t in self.thresholds],
            "markers": [m.to_dict() for m in self.markers],
            "reasons": [r.to_dict() for r in self.reasons],
            "stages": [s.to_dict() for s in self.stages],
            "signals": [s.to_dict() for s in self.signals],
            "warnings": list(self.warnings),
        }


def build_policy_table() -> PolicyTable:
    """Return the policy plus any structural inconsistencies detected.

    Warnings are findings, not failures. They exist because two real
    divergences were found while assembling this table and would otherwise have
    stayed buried in the code.
    """
    warnings: list[str] = []

    # 1) Script-ratio threshold disagrees between the two modules.
    high = next(t.value for t in THRESHOLDS if t.name == "HIGH_SCRIPT_RATIO")
    low = next(t.value for t in THRESHOLDS if t.name == "LOW_DENSITY_SCRIPT_RATIO")
    if high != low:
        warnings.append(
            f"script_ratio threshold differs by module: recovery uses {high}, "
            f"fetch_escalation low-density uses {low}. Same signal, two bars."
        )

    # 2) NON_HTML_PREFIXES is declared in both modules.
    warnings.append(
        "NON_HTML_PREFIXES is defined twice (recovery.py and fetch_escalation.py). "
        "They agree today; nothing enforces that."
    )

    # 3) Every browser-escalating reason must map to an action of BROWSER.
    for rule in REASON_RULES:
        if rule.escalates and rule.action != RecoveryAction.BROWSER.value:
            warnings.append(f"{rule.reason} is marked escalates=True but action is {rule.action}")

    # 4) Every declared reason must be a real enum member.
    known = {r.value for r in RecoveryReason}
    for rule in REASON_RULES:
        if rule.reason not in known:
            warnings.append(f"policy lists unknown RecoveryReason: {rule.reason}")
    missing = known - {rule.reason for rule in REASON_RULES}
    if missing:
        warnings.append(f"RecoveryReason members with no policy entry: {sorted(missing)}")

    # 5) Every escalation signal reason must be a real EscalationReason,
    #    except the explicit non-escalation sentinel.
    esc_known = {r.value for r in EscalationReason}
    for sig in ESCALATION_SIGNALS:
        if sig.reason not in esc_known and sig.reason != "NOT_ESCALATED":
            warnings.append(f"escalation signal {sig.name} names unknown reason {sig.reason}")

    return PolicyTable(warnings=warnings)


def render_markdown(table: PolicyTable | None = None) -> str:
    """Render the policy as a reviewable document."""
    t = table or build_policy_table()
    lines: list[str] = ["# Fetch Recovery Policy", ""]

    lines += ["## Thresholds", "", "| Name | Value | Unit | Module | Rationale |", "|---|---|---|---|---|"]
    for th in t.thresholds:
        lines.append(f"| `{th.name}` | {th.value} | {th.unit} | {th.module} | {th.rationale} |")

    lines += [
        "",
        "## Classification stages (first match wins)",
        "",
        "| # | Stage | Condition | Yields |",
        "|---|---|---|---|",
    ]
    for st in t.stages:
        lines.append(f"| {st.order} | {st.name} | {st.condition} | {', '.join(st.yields)} |")

    lines += [
        "",
        "## Reason to action",
        "",
        "| Reason | Action | Confidence | Escalates | Rationale |",
        "|---|---|---|---|---|",
    ]
    for r in t.reasons:
        lines.append(
            f"| `{r.reason}` | {r.action} | {r.confidence} | {'yes' if r.escalates else 'no'} | {r.rationale} |"
        )

    lines += [
        "",
        "## Browser escalation signals",
        "",
        "| Signal | Condition | Reason | Confidence |",
        "|---|---|---|---|",
    ]
    for s in t.signals:
        lines.append(f"| {s.name} | {s.condition} | {s.reason} | {s.confidence} |")

    lines += ["", "## Marker sets", "", "| Set | Count | Purpose |", "|---|---|---|"]
    for m in t.markers:
        lines.append(f"| `{m.name}` | {len(m.markers)} | {m.purpose} |")

    if t.warnings:
        lines += ["", "## Structural findings", ""]
        lines += [f"- {w}" for w in t.warnings]

    return "\n".join(lines) + "\n"
