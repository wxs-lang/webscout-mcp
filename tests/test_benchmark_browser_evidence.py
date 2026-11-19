"""Pin the browser_failed evidence rule with the exact shape #203 produced.

#203's benchmark failed on:

    REGRESSION  live: reuters: pass -> degraded
    live: reuters  degraded  2444 chars, grade=usable, status=200   <- previous run
    live: medium   degraded  134 chars, grade=empty, outcome=browser_failed

Its base contained the capability fix; it did not help because the PREVIOUS record
predated `browser_available`. The evidence that DOES survive the upgrade is the
scenario detail string.

These tests use the detail text verbatim from the CI log.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import benchmark_tools as bt


def _run(browser, scenarios, egress="datacenter"):
    """scenarios: list of (name, verdict, detail, error)."""
    return {
        "context": {"egress": egress, "browser_available": browser},
        "local": {"total": 15, "passed": 15, "failed": 0, "pass_rate": 100.0},
        "live": {
            "counts": {"pass": 0, "degraded": 0, "fail": 0},
            "total": len(scenarios),
            "scenarios": [{"name": n, "verdict": v, "detail": d, "error": e} for n, v, d, e in scenarios],
        },
    }


def test_browser_failed_scenario_is_not_scored_as_regression():
    """A PERSISTENT drop that the current run explains by a missing browser.

    The anti-noise rule only scores a drop that looks persistent (worse in two
    consecutive runs). That is the shape that failed #203: once the old baseline
    had recorded `pass`, every later browser-less run kept the drop alive.

    The record before the previous one predates `browser_available`, which is why
    the run-level capability comparison cannot catch it — the evidence has to come
    from the scenario detail.
    """
    old_pass = {
        "context": {"egress": "datacenter"},  # no browser_available field
        "local": {"total": 15, "passed": 15, "failed": 0, "pass_rate": 100.0},
        "live": {
            "counts": {"pass": 1, "degraded": 0, "fail": 0},
            "total": 1,
            "scenarios": [
                {
                    "name": "live: reuters",
                    "verdict": "pass",
                    "detail": "2444 chars, grade=usable, status=200",
                    "error": None,
                }
            ],
        },
    }
    # previous run: already degraded (this is what makes it look persistent)
    previous = _run(
        False,
        [
            ("live: reuters", "degraded", "140 chars, grade=empty, outcome=browser_failed", None),
        ],
    )
    current = _run(
        False,
        [
            ("live: reuters", "degraded", "134 chars, grade=empty, outcome=browser_failed", None),
        ],
    )

    # sanity: without evidence this shape WOULD be scored
    no_evidence = _run(False, [("live: reuters", "degraded", "134 chars, grade=empty, outcome=n/a", None)])
    baseline_diff = bt._diff_verdicts(old_pass, previous, no_evidence)
    assert baseline_diff["regressions"], "precondition: a persistent pass->degraded without evidence is a regression"

    diff = bt._diff_verdicts(old_pass, previous, current)

    assert diff["regressions"] == [], "a run that could not launch a browser cannot be scored against one that could"
    moved = [f for f in diff["flapping"] if f["name"] == "live: reuters"]
    assert moved, "the change must still be reported"
    assert "browser_failed" in moved[0].get("reason", "")


def test_a_scenario_without_browser_evidence_still_scores():
    """The exemption must be evidence-based, not a blanket pass."""
    previous = _run(
        True,
        [
            ("live: example", "pass", "156 chars, grade=usable, status=200", None),
        ],
    )
    current = _run(
        True,
        [
            ("live: example", "fail", "0 chars, grade=empty, outcome=n/a", None),
        ],
    )

    diff = bt._diff_verdicts(previous, previous, current)

    assert diff["incomparable"] is False
    # single flip stays flapping by the anti-noise rule, so assert it is NOT hidden
    assert diff["flapping"], "a real change must be reported"
    assert all("browser_failed" not in (f.get("reason") or "") for f in diff["flapping"])


def test_browser_evidence_does_not_mask_a_different_scenario():
    """Only the scenarios that show the evidence are exempt."""
    previous = _run(
        True,
        [
            ("live: blocked", "pass", "2000 chars, grade=usable, status=200", None),
            ("live: unrelated", "pass", "3000 chars, grade=usable, status=200", None),
        ],
    )
    current = _run(
        False,
        [
            ("live: blocked", "degraded", "134 chars, grade=empty, outcome=browser_failed", None),
            ("live: unrelated", "fail", "0 chars, grade=empty, outcome=n/a", None),
        ],
    )

    diff = bt._diff_verdicts(previous, previous, current)

    # 'blocked' is exempt; 'unrelated' has no evidence and stays visible
    names_in_flapping = {f["name"] for f in diff["flapping"]}
    assert "live: blocked" in names_in_flapping
    assert "live: unrelated" in names_in_flapping
    assert diff["contract_breaks"] == [] or any(f["name"] == "live: unrelated" for f in diff["flapping"])


def test_the_helper_reads_details_not_names():
    run = _run(
        False,
        [
            ("live: a", "degraded", "x chars, outcome=browser_failed", None),
            ("live: b", "degraded", "x chars, grade=empty", None),
        ],
    )
    assert bt._live_browser_failed(run) == {"live: a"}
