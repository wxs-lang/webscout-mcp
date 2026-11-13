"""Egress-aware comparison: a network difference is not a code regression.

Measured across this project, same code:

    amazon   residential   5/5 pass at 7285-7435 chars
             datacenter    repeatedly degraded, 157-char challenge

Both readings are true; they answer different questions. Recording the class makes the
difference visible, and comparing only within a class stops it being reported as a change in
the product.
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "benchmark_tools.py"


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location("bench_egress", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["bench_egress"] = module
    spec.loader.exec_module(module)
    return module


def _run(egress: str, when: str, **verdicts: str) -> dict:
    return {
        "recorded_at": when,
        "context": {"egress": egress} if egress else {},
        "live": {
            "scenarios": [{"name": k, "verdict": v} for k, v in verdicts.items()],
            "skipped": [],
        },
    }


def _bucket(diff: dict) -> str:
    for key in ("regressions", "contract_breaks", "flapping"):
        if diff.get(key):
            return key
    return "none"


def test_egress_is_detected_for_a_local_process(monkeypatch, bench):
    for name in ("GITHUB_ACTIONS", "GITLAB_CI", "CIRCLECI", "BUILDKITE", "TF_BUILD", "JENKINS_URL"):
        monkeypatch.delenv(name, raising=False)
    ctx = bench._egress_context()
    assert ctx["egress"] == "local"


def test_egress_is_detected_under_ci(monkeypatch, bench):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_NAME", "GitHub Actions 42")
    ctx = bench._egress_context()
    assert ctx["egress"] == "datacenter"
    assert ctx["runner"] == "GitHub Actions 42"


def test_a_cross_egress_drop_is_not_a_regression(bench):
    """The confusion that made eight PRs report a regression they could not cause."""
    diff = bench._diff_verdicts(
        _run("local", "2026-11-13T01:00:00+00:00", amazon="pass"),
        _run("local", "2026-11-13T00:00:00+00:00", amazon="degraded"),
        _run("datacenter", "2026-11-13T02:00:00+00:00", amazon="degraded"),
    )
    assert diff["regressions"] == []
    assert diff["flapping"], "the movement is still reported, with the reason"
    assert diff["egress_mismatch"] is True
    assert "egress" in diff["flapping"][0]["reason"]


def test_a_same_egress_decline_is_still_a_regression(bench):
    """The guard must not defang the check it is protecting."""
    diff = bench._diff_verdicts(
        _run("datacenter", "2026-11-13T01:00:00+00:00", amazon="pass"),
        _run("datacenter", "2026-11-13T00:00:00+00:00", amazon="degraded"),
        _run("datacenter", "2026-11-13T02:00:00+00:00", amazon="degraded"),
    )
    assert diff["regressions"], "a real decline within one environment must still gate"
    assert diff["egress_mismatch"] is False


def test_a_cross_egress_contract_break_is_downgraded_with_a_reason(bench):
    diff = bench._diff_verdicts(
        _run("local", "2026-11-13T01:00:00+00:00", a="degraded"),
        _run("local", "2026-11-13T00:00:00+00:00", a="degraded"),
        _run("datacenter", "2026-11-13T02:00:00+00:00", a="fail"),
    )
    assert diff["contract_breaks"] == []
    assert any("egress" in item.get("reason", "") for item in diff["flapping"])


def test_records_without_egress_still_compare(bench):
    """History written before this field existed must keep working."""
    diff = bench._diff_verdicts(
        _run("", "2026-11-13T01:00:00+00:00", amazon="pass"),
        _run("", "2026-11-13T00:00:00+00:00", amazon="degraded"),
        _run("", "2026-11-13T02:00:00+00:00", amazon="degraded"),
    )
    assert diff["regressions"], "an absent marker must not suppress a real regression"
    assert diff["egress_mismatch"] is False


def test_the_report_states_the_egress_it_compared(bench):
    diff = bench._diff_verdicts(
        _run("local", "2026-11-13T01:00:00+00:00", a="pass"),
        {},
        _run("datacenter", "2026-11-13T02:00:00+00:00", a="pass"),
    )
    assert diff["egress"] == {"previous": "local", "current": "datacenter"}
