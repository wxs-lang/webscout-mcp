"""Reproduce main's red tool-benchmark as a test, then prove the fix.

The scenario, from the actual CI log:

    run A (had a browser):   live: amazon pass
    run B (no browser):      live: amazon degraded
    both:                    egress=datacenter, same commit
    diff:                    REGRESSION live: amazon: pass -> degraded  -> exit 1

The live verdict logic already said a site declining to serve us is a capability
boundary, "not a regression". The history diff disagreed, because it only knew how
to exempt a change when the EGRESS class differed. A runner losing its Playwright
browser is the same kind of difference, so it is now exempted the same way.

The benchmark deliberately treats a single flip as noise, so a regression needs
two consecutive bad runs. These tests respect that rule; they do not work around
it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import benchmark_tools as bt


def _run(browser: bool, amazon: str, egress: str = "datacenter") -> dict:
    return {
        "context": {"egress": egress, "browser_available": browser},
        "local": {"total": 15, "passed": 15, "failed": 0, "pass_rate": 100.0},
        "live": {
            "counts": {"pass": 4, "degraded": 1, "fail": 0},
            "total": 5,
            "scenarios": [
                {"name": "live: wikipedia", "verdict": "pass", "detail": "", "error": None},
                {"name": "live: amazon", "verdict": amazon, "detail": "", "error": None},
            ],
        },
    }


def test_lost_browser_does_not_fail_the_run():
    """main's failure, exactly: the run must not exit 1 for this."""
    previous = _run(browser=True, amazon="pass")
    current = _run(browser=False, amazon="degraded")

    diff = bt._diff_verdicts(previous, previous, current)

    assert diff["capability_mismatch"] is True, "a run that lost its browser is not comparable to one that had it"
    assert diff["incomparable"] is True
    assert diff["regressions"] == [], (
        "this is what made main red: a capability difference was scored as a code regression"
    )
    assert diff["contract_breaks"] == []


def test_the_change_is_still_reported():
    """Exempt from scoring, not hidden: the operator must still see it."""
    previous = _run(browser=True, amazon="pass")
    current = _run(browser=False, amazon="degraded")

    diff = bt._diff_verdicts(previous, previous, current)

    moved = [f for f in diff["flapping"] if f["name"] == "live: amazon"]
    assert moved, "the verdict change must appear in the report"
    assert moved[0]["from"] == "pass" and moved[0]["to"] == "degraded"


def test_persistent_drop_with_equal_capability_is_still_a_regression():
    """The fix must not deafen the gate to real regressions."""
    two_runs_ago = _run(browser=True, amazon="pass")
    previous = _run(browser=True, amazon="fail")
    current = _run(browser=True, amazon="fail")

    diff = bt._diff_verdicts(two_runs_ago, previous, current)

    assert diff["incomparable"] is False
    assert diff["regressions"] == [{"name": "live: amazon", "from": "pass", "to": "fail"}]


def test_single_flip_stays_noise():
    """Pre-existing behaviour, pinned so a future change cannot quietly alter it."""
    previous = _run(browser=True, amazon="pass")
    current = _run(browser=True, amazon="fail")

    diff = bt._diff_verdicts(previous, previous, current)

    assert diff["regressions"] == []
    assert diff["flapping"], "one flip is reported, not scored"


def test_egress_mismatch_still_exempts():
    """The rule this was modelled on must keep working."""
    previous = _run(browser=True, amazon="pass", egress="local")
    current = _run(browser=True, amazon="degraded", egress="datacenter")

    diff = bt._diff_verdicts(previous, previous, current)

    assert diff["egress_mismatch"] is True
    assert diff["incomparable"] is True
    assert diff["regressions"] == []


def test_records_without_the_field_are_not_assumed_incomparable():
    """Old history entries predate browser_available; absence is not a mismatch."""
    previous = {
        "context": {"egress": "datacenter"},
        "local": {"total": 15, "passed": 15, "failed": 0, "pass_rate": 100.0},
        "live": {
            "counts": {"pass": 5},
            "total": 5,
            "scenarios": [{"name": "live: amazon", "verdict": "pass", "detail": "", "error": None}],
        },
    }
    current = _run(browser=False, amazon="degraded")

    diff = bt._diff_verdicts(previous, previous, current)

    assert diff["capability_mismatch"] is False, (
        "only an observed difference counts; a missing field must not exempt a run"
    )
