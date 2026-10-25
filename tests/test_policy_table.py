"""The policy table must describe the code that actually runs.

A policy document that drifts from its implementation is worse than none: it
becomes a confident, wrong answer to "why did this request escalate?". So every
value in recovery_policy is asserted against the live module here. If someone
changes a threshold in recovery.py and forgets the table, this fails.
"""

from __future__ import annotations

import inspect

import pytest

from webscout_mcp import fetch_escalation, recovery, recovery_policy
from webscout_mcp.fetch_escalation import EscalationReason
from webscout_mcp.recovery import RecoveryAction, RecoveryReason


def _table_by_name() -> dict[str, recovery_policy.Threshold]:
    return {t.name: t for t in recovery_policy.THRESHOLDS}


# --- Thresholds must equal the live constants ----------------------------


@pytest.mark.parametrize(
    ("table_name", "module", "attr"),
    [
        ("SHORT_PAGE_TEXT_CHARS", recovery, "_SHORT_PAGE_TEXT_CHARS"),
        ("THIN_SHELL_TEXT_CHARS", recovery, "_THIN_SHELL_TEXT_CHARS"),
        ("LARGE_HTML_CHARS", recovery, "_LARGE_HTML_CHARS"),
        ("HIGH_SCRIPT_RATIO", recovery, "_HIGH_SCRIPT_RATIO"),
        ("MIN_403_HTML_BYTES", recovery, "_MIN_403_HTML_BYTES"),
        ("MIN_TEXT_CHARS_FOR_REAL_PAGE", fetch_escalation, "_MIN_TEXT_CHARS_FOR_REAL_PAGE"),
        ("MIN_HTML_BYTES_FOR_LOW_DENSITY", fetch_escalation, "_MIN_HTML_BYTES_FOR_LOW_DENSITY"),
        ("MIN_PAGE_BYTES_FOR_LOW_QUALITY", fetch_escalation, "_MIN_PAGE_BYTES_FOR_LOW_QUALITY"),
    ],
)
def test_table_threshold_matches_live_constant(table_name, module, attr):
    table = _table_by_name()
    assert table_name in table, f"{table_name} missing from the policy table"
    assert table[table_name].value == getattr(module, attr), (
        f"{table_name} in the policy table says {table[table_name].value}, "
        f"but {module.__name__}.{attr} is {getattr(module, attr)}"
    )


def test_low_density_script_ratio_is_still_hardcoded():
    """Documents a known divergence so it cannot disappear unnoticed.

    fetch_escalation uses a literal ``sr > 0.2`` while recovery declares
    HIGH_SCRIPT_RATIO = 0.15. Same signal, two bars. The table records 0.2 as
    LOW_DENSITY_SCRIPT_RATIO; this test pins the literal so that whoever
    unifies them has to update both places deliberately.
    """
    src = inspect.getsource(fetch_escalation.should_escalate_to_browser)
    assert "sr > 0.2" in src, (
        "the hardcoded script ratio changed; update LOW_DENSITY_SCRIPT_RATIO in "
        "recovery_policy and the warning in build_policy_table()"
    )
    table = _table_by_name()
    assert table["LOW_DENSITY_SCRIPT_RATIO"].value == 0.2
    assert table["HIGH_SCRIPT_RATIO"].value == 0.15, "the two bars are expected to differ today"


# --- Marker sets must equal the live tuples ------------------------------


@pytest.mark.parametrize(
    ("table_name", "live"),
    [
        ("CHALLENGE_MARKERS", fetch_escalation._CHALLENGE_MARKERS),
        ("JS_PLACEHOLDER_MARKERS", fetch_escalation._JS_PLACEHOLDER_MARKERS),
        ("LOGIN_WALL_MARKERS", recovery._LOGIN_WALL_MARKERS),
        ("NON_HTML_PREFIXES", recovery._NON_HTML_PREFIXES),
    ],
)
def test_marker_set_matches_live_tuple(table_name, live):
    table = {m.name: m for m in recovery_policy.MARKER_SETS}
    assert table_name in table
    assert table[table_name].markers == tuple(live), f"{table_name} differs from the live tuple"


def test_duplicated_non_html_prefixes_agree():
    """The tuple exists in two modules. They must not silently diverge."""
    assert recovery._NON_HTML_PREFIXES == fetch_escalation._NON_HTML_PREFIXES


# --- Reason coverage ----------------------------------------------------


def test_every_recovery_reason_has_a_policy_entry():
    table_reasons = {r.reason for r in recovery_policy.REASON_RULES}
    live = {r.value for r in RecoveryReason}
    assert live == table_reasons, f"missing: {sorted(live - table_reasons)}, extra: {sorted(table_reasons - live)}"


def test_every_policy_action_is_a_real_recovery_action():
    valid = {a.value for a in RecoveryAction}
    for rule in recovery_policy.REASON_RULES:
        assert rule.action in valid, f"{rule.reason} -> {rule.action} is not a RecoveryAction"


def test_escalating_reasons_map_to_the_browser_action():
    for rule in recovery_policy.REASON_RULES:
        if rule.escalates:
            assert rule.action == RecoveryAction.BROWSER.value, (
                f"{rule.reason} claims escalates=True but action is {rule.action}"
            )


def test_exactly_four_reasons_escalate():
    """Four browser reasons is a fact worth pinning.

    If a fifth appears, browser escalation got broader - which would raise cost
    per request and needs a deliberate decision, not an accident.
    """
    escalating = {r.reason for r in recovery_policy.REASON_RULES if r.escalates}
    assert escalating == {"SOFT_BLOCK", "JS_REQUIRED", "LOW_CONTENT_DENSITY", "LOW_QUALITY"}


def test_escalation_signals_name_real_reasons():
    valid = {r.value for r in EscalationReason}
    for sig in recovery_policy.ESCALATION_SIGNALS:
        if sig.reason == "NOT_ESCALATED":
            continue
        assert sig.reason in valid, f"{sig.name} names unknown reason {sig.reason}"


# --- Stage list must match the real priority chain ----------------------


def test_stage_order_matches_the_classify_docstring():
    """The chain order is documented in classify_recovery itself.

    Keeping the table and the docstring in step means a reviewer reading either
    one gets the same answer about what wins when several conditions hold.
    """
    doc = (inspect.getdoc(recovery.classify_recovery) or "").lower()
    for marker in (
        "legal/geo",
        "transport",
        "access denial",
        "non-html",
        "truncation",
        "browser signals",
        "complete",
    ):
        assert marker in doc, f"classify_recovery docstring lost '{marker}'"


def test_classify_stages_are_numbered_contiguously():
    orders = [s.order for s in recovery_policy.CLASSIFY_STAGES]
    assert orders == list(range(1, len(orders) + 1))


def test_every_stage_yields_a_known_reason():
    valid = {r.value for r in RecoveryReason}
    for stage in recovery_policy.CLASSIFY_STAGES:
        for reason in stage.yields:
            assert reason in valid, f"stage {stage.name} yields unknown reason {reason}"


# --- The structural findings must keep being reported -------------------


def test_build_reports_the_known_divergences():
    table = recovery_policy.build_policy_table()
    joined = " ".join(table.warnings)
    assert "script_ratio threshold differs" in joined
    assert "NON_HTML_PREFIXES is defined twice" in joined


def test_build_reports_no_unexpected_problems():
    """Only the two documented findings; anything else is a new bug."""
    table = recovery_policy.build_policy_table()
    unexpected = [
        w
        for w in table.warnings
        if "script_ratio threshold differs" not in w and "NON_HTML_PREFIXES is defined twice" not in w
    ]
    assert unexpected == [], f"new structural findings: {unexpected}"


# --- Read-only guarantee ------------------------------------------------


def test_importing_the_table_does_not_change_classification():
    """This module describes policy; it must not alter a verdict.

    Re-classification after importing recovery_policy must be byte-identical to
    the policy the code already had.
    """
    from webscout_mcp.fetch_provider import FetchResponse

    resp = FetchResponse(
        url="https://example.com/a",
        final_url="https://example.com/a",
        status_code=200,
        provider="http",
        content="x" * 5000,
        content_type="text/html",
        extracted=True,
        metadata={},
    )
    before = recovery.classify_recovery(resp)
    # Touch the table, then re-classify.
    recovery_policy.build_policy_table()
    after = recovery.classify_recovery(resp)
    assert before.reason is after.reason
    assert before.action is after.action
    assert before.confidence == after.confidence


def test_markdown_renders_every_section():
    md = recovery_policy.render_markdown()
    for heading in (
        "# Fetch Recovery Policy",
        "## Thresholds",
        "## Classification stages",
        "## Reason to action",
        "## Browser escalation signals",
        "## Marker sets",
        "## Structural findings",
    ):
        assert heading in md, f"missing section: {heading}"
