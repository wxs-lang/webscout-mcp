"""The policy table must constrain the classifier, not merely describe it.

Direction 3's acceptance criterion. Before this change, editing
REASON_RULES left classify_recovery untouched: the table was documentation
with a test asserting the thresholds matched, while the action and confidence
were literals at 28 return sites. A reader could change a row, see green tests,
and change nothing.

Now:
  - 13 sites take both action and confidence from the table
  - 14 sites take the action from the table and pass an explicit confidence,
    because the same reason carries different confidence depending on which
    trigger fired (SOFT_BLOCK 0.7..0.95, ACCESS_DENIED 0.5..0.9). The table
    documents the representative value; the site owns the nuance.
  - 1 site (AMBIGUOUS -> BROWSER at 0.6) still diverges from the table's
    NONE. That divergence is real and is asserted below so it cannot drift
    silently in either direction.

These tests fail if a future edit makes the table descriptive again.
"""

from __future__ import annotations

import dataclasses

import pytest

from webscout_mcp import recovery_policy
from webscout_mcp.fetch_provider import FetchResponse
from webscout_mcp.orchestration import recovery as rec


def _resp(**kw) -> FetchResponse:
    base = {
        "url": "https://x.test/",
        "final_url": "https://x.test/",
        "status_code": 200,
        "provider": "http",
        "content": "hello world " * 100,
        "content_type": "text/html",
    }
    base.update(kw)
    return FetchResponse(**base)


@pytest.fixture
def restore_policy_cache():
    """_POLICY_BY_REASON is a cache; tests that patch it must not leak."""
    saved = dict(rec._POLICY_BY_REASON)
    yield
    rec._POLICY_BY_REASON.clear()
    rec._POLICY_BY_REASON.update(saved)


def test_editing_the_action_changes_the_decision(restore_policy_cache):
    """The load-bearing check: change the row, the classifier follows."""
    before = rec.classify_recovery(_resp(status_code=451))
    assert before.reason.value == "LEGAL_OR_GEO_BLOCK"
    assert before.action.value == "STOP"

    row = next(r for r in recovery_policy.REASON_RULES if r.reason == "LEGAL_OR_GEO_BLOCK")
    rec._POLICY_BY_REASON.clear()
    rec._POLICY_BY_REASON["LEGAL_OR_GEO_BLOCK"] = dataclasses.replace(row, action="RETRY_LATER")

    after = rec.classify_recovery(_resp(status_code=451))
    assert after.action.value == "RETRY_LATER", (
        "the classifier ignored a policy-table edit, so the table is descriptive again"
    )


def test_editing_the_confidence_changes_the_decision(restore_policy_cache):
    row = next(r for r in recovery_policy.REASON_RULES if r.reason == "LEGAL_OR_GEO_BLOCK")
    rec._POLICY_BY_REASON.clear()
    rec._POLICY_BY_REASON["LEGAL_OR_GEO_BLOCK"] = dataclasses.replace(row, confidence=0.11)

    d = rec.classify_recovery(_resp(status_code=451))
    assert d.confidence == pytest.approx(0.11)


def test_a_reason_with_no_policy_row_is_loud(restore_policy_cache, monkeypatch):
    """A missing row is a defect in the table, not a silent default.

    Clearing the cache is not enough: _policy_rule rebuilds it from the table on
    first use. So patch the table itself (a tuple, hence monkeypatch.setattr
    rather than item assignment) for the duration.
    """
    from webscout_mcp.orchestration.recovery import RecoveryReason

    pruned = tuple(r for r in recovery_policy.REASON_RULES if r.reason != "AMBIGUOUS")
    monkeypatch.setattr(recovery_policy, "REASON_RULES", pruned)
    rec._POLICY_BY_REASON.clear()

    with pytest.raises(KeyError, match="REASON_RULES"):
        rec._d(RecoveryReason.AMBIGUOUS, confidence=0.5)


def test_the_one_known_divergence_is_pinned():
    """AMBIGUOUS maps to NONE in the table but BROWSER at one call site.

    Pinning it makes the disagreement visible: either the table row or the call
    site should change, and whichever happens will break this test and force a
    decision. Silently "fixing" one side would hide that a policy question was
    open.
    """
    row = next(r for r in recovery_policy.REASON_RULES if r.reason == "AMBIGUOUS")
    assert row.action == "NONE"
    # the call site that disagrees, found by its distinctive confidence
    import inspect
    import re

    src = inspect.getsource(rec.classify_recovery)
    assert re.search(r"RecoveryAction\.BROWSER,\s*0\.6", src), (
        "the AMBIGUOUS/BROWSER@0.6 divergence is gone; if it was resolved on "
        "purpose, update the table row and delete this test"
    )
