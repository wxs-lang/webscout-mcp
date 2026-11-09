"""History tracking for the live benchmark.

The value of a time series is deciding what a change means before recording it, so most of
these tests pin the classification rather than the file format:

- a `pass` that worsens is a regression (the chosen bar: a site adding a challenge page is
  not our defect, and scoring it would swamp the signal)
- `degraded` -> `fail` is a contract break, reported separately
- transitions involving `skip` are coverage facts, never scored - otherwise running on two
  machines with different network access would report a regression on every alternation
- a first run is never a regression
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "benchmark_tools.py"


@pytest.fixture(scope="module")
def bench():
    spec = importlib.util.spec_from_file_location("bench_history", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Register before executing: @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is null for an unregistered module.
    sys.modules["bench_history"] = module
    spec.loader.exec_module(module)
    return module


def _diff(bench, before: dict, after: dict, earlier: dict | None = None) -> dict:
    """Compare two runs, treating `earlier` as the run before `before`.

    Without `earlier`, a worsening transition is a first flip - which the production code
    reports as `flapping` rather than a regression, because one flip is what an unstable
    site produces.
    """
    return bench._diff_verdicts(before, earlier or {}, after)


def _run(**verdicts: str) -> dict:
    return {
        "live": {
            "scenarios": [{"name": k, "verdict": v} for k, v in verdicts.items()],
            "skipped": [],
        }
    }


def test_pass_to_degraded_is_a_regression(bench):
    """A single flip is recorded as flapping; a second consecutive one is a regression.

    Measured: amazon's anti-bot decides per request, and three consecutive local runs gave
    6781, 4328 and 6221 chars - all successful. Counting one flip as a regression made CI
    red on noise, which trains people to re-run until green.
    """
    first = _diff(bench, _run(a="pass"), _run(a="degraded"))
    assert first["regressions"] == []
    assert first["flapping"] == [{"name": "a", "from": "pass", "to": "degraded"}]

    second = _diff(bench, _run(a="pass"), _run(a="degraded"), earlier=_run(a="degraded"))
    assert second["regressions"] == [{"name": "a", "from": "pass", "to": "degraded"}]
    assert second["flapping"] == []


def test_pass_to_fail_is_a_regression(bench):
    """Same rule: one flip flaps, two consecutive count."""
    assert _diff(bench, _run(a="pass"), _run(a="fail"))["regressions"] == []
    escalated = _diff(bench, _run(a="pass"), _run(a="fail"), earlier=_run(a="fail"))
    assert len(escalated["regressions"]) == 1


def test_degraded_to_fail_is_a_contract_break_not_a_regression(bench):
    """A contract break is more serious than a capability boundary, and separate."""
    diff = _diff(bench, _run(a="degraded"), _run(a="fail"))
    assert diff["regressions"] == []
    assert diff["contract_breaks"] == [{"name": "a", "from": "degraded", "to": "fail"}]


@pytest.mark.parametrize(
    ("before", "after"),
    [("degraded", "pass"), ("fail", "pass"), ("fail", "degraded")],
)
def test_improvements_are_recoveries(bench, before, after):
    diff = _diff(bench, _run(a=before), _run(a=after))
    assert diff["recoveries"] == [{"name": "a", "from": before, "to": after}]
    assert diff["regressions"] == []


def test_skip_is_coverage_not_quality(bench):
    """pass -> skip must not be a regression.

    Measured reason: `broken_links` passes on CI and is skipped here, because its
    SSRF-pinned transport targets a bare IP that this network refuses at the TLS layer.
    Ranking skip as worse than fail made that alternation read as a regression every time
    the benchmark ran on a different machine.
    """
    diff = _diff(bench, _run(a="pass"), _run(a="skip"))
    assert diff["regressions"] == []
    assert diff["newly_skipped"] == [{"name": "a", "from": "pass", "to": "skip"}]


def test_unskip_is_reported_separately(bench):
    diff = _diff(bench, _run(a="skip"), _run(a="pass"))
    assert diff["recoveries"] == []
    assert diff["unskipped"] == [{"name": "a", "from": "skip", "to": "pass"}]


def test_unchanged_verdicts_produce_nothing(bench):
    diff = _diff(bench, _run(a="pass", b="degraded"), _run(a="pass", b="degraded"))
    assert not any(diff[key] for key in diff)


def test_new_and_missing_scenarios_are_reported(bench):
    diff = _diff(bench, _run(a="pass"), _run(a="pass", b="pass"))
    assert diff["appeared"] == ["b"]
    diff = _diff(bench, _run(a="pass", b="pass"), _run(a="pass"))
    assert diff["disappeared"] == ["b"]


def test_first_run_has_no_previous_entry(bench, tmp_path):
    history = tmp_path / "h.jsonl"
    previous, before = bench._record_run(history, _run(a="pass"), {"recorded_at": "2026-01-01T00:00:00+00:00"})
    assert previous == {} and before == {}
    assert history.exists()


def test_history_appends_rather_than_rewrites(bench, tmp_path):
    """A whole-file rewrite loses every earlier run if it crashes partway."""
    history = tmp_path / "h.jsonl"
    for i in range(3):
        bench._record_run(history, _run(a="pass"), {"recorded_at": f"2026-01-0{i + 1}T00:00:00+00:00"})
    lines = history.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["recorded_at"][:10] for line in lines] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]


def test_a_truncated_final_line_does_not_lose_the_history(bench, tmp_path):
    """What a killed process leaves behind."""
    history = tmp_path / "h.jsonl"
    bench._record_run(history, _run(a="pass"), {"recorded_at": "2026-01-01T00:00:00+00:00"})
    with history.open("a", encoding="utf-8") as handle:
        handle.write('{"recorded_at": "2026-01-02T00:0')

    previous, _before = bench._record_run(history, _run(a="pass"), {"recorded_at": "2026-01-03T00:00:00+00:00"})
    assert previous.get("recorded_at") == "2026-01-01T00:00:00+00:00"
    assert len(history.read_text(encoding="utf-8").splitlines()) == 3


def test_timestamps_are_timezone_aware(bench):
    """Naive timestamps would compare as if they were UTC."""
    stamp = bench._utc_now()
    assert stamp.endswith("+00:00"), stamp


def test_history_is_opt_in():
    """Without --history the behaviour must be unchanged."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"--history"' in source
    assert "if args.history is not None:" in source


def test_regression_only_fails_the_run_when_a_history_was_read(bench, tmp_path):
    """A regression needs something to compare against."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert "if args.strict and history_diff:" in source


# --- flap suppression -------------------------------------------------
# One flip is what an unstable site produces. Measured on amazon: three consecutive local
# runs returned 6781, 4328 and 6221 chars, all successful. A gate that goes red on that
# trains people to re-run until green, which is how a real regression gets waved through.


def test_a_single_flip_is_reported_but_does_not_gate(bench):
    diff = _diff(bench, _run(amazon="pass"), _run(amazon="degraded"))
    assert diff["flapping"], "a flip must still be recorded"
    assert diff["regressions"] == [], "one flip must not gate the build"


def test_a_persistent_drop_does_gate(bench):
    diff = _diff(bench, _run(amazon="pass"), _run(amazon="degraded"), earlier=_run(amazon="degraded"))
    assert diff["regressions"], "a second consecutive drop is a real regression"
    assert diff["flapping"] == []


def test_no_earlier_entry_cannot_produce_a_regression(bench):
    """A first run, or a newly added scenario, must never manufacture one."""
    diff = _diff(bench, _run(newthing="pass"), _run(newthing="fail"), earlier={})
    assert diff["regressions"] == []
    assert diff["flapping"], diff


def test_a_contract_break_is_never_downgraded_to_flapping(bench):
    """degraded -> fail means the pipeline stopped explaining itself, which no site causes."""
    diff = _diff(bench, _run(a="degraded"), _run(a="fail"), earlier=_run(a="degraded"))
    assert diff["contract_breaks"], diff
    assert diff["flapping"] == []
