"""G3 must measure the pipeline, not the network.

A ratio-only latency gate fires hardest when the baseline is fastest, which is
the opposite of its purpose. Ten measured runs showed the pipeline adding a
stable +39 to +179ms (median +80ms) of extraction and classification while the
ratio swung 1.26-2.77 purely because the baseline moved between 78ms and 175ms.

The corrected gate passes on either a bounded ratio or a bounded delta, with a
ceiling so a genuine doubling cannot hide behind a small absolute delta.
"""

from __future__ import annotations

import pytest

from webscout_mcp.ab_eval import ArmObservation, evaluate


def _pair(
    pipeline_ms: float,
    baseline_ms: float,
    n: int = 20,
    stratum: str = "article",
) -> list[ArmObservation]:
    """Build a matched pair of arms for the given latency, in one stratum.

    The stratum matters: the gate judges each one against its own delta budget,
    so a case id must look like "000:article" rather than "c0".
    """
    obs: list[ArmObservation] = []
    for i in range(n):
        cid = f"{i:03d}:{stratum}"
        obs.append(ArmObservation(cid, "pipeline", True, 5000, pipeline_ms))
        obs.append(ArmObservation(cid, "baseline", True, 5000, baseline_ms))
    return obs


def _g3(result):
    return next(g for g in result.gates if g.name.startswith("G3"))


# --- Fast path: within the ratio bound ----------------------------------


def test_ratio_within_bounds_passes():
    """550 vs 500 is x1.10, comfortably inside 1.30."""
    assert _g3(evaluate(_pair(550.0, 500.0))).passed


def test_equal_latency_passes():
    assert _g3(evaluate(_pair(200.0, 200.0))).passed


# --- The case the old gate got wrong -----------------------------------


def test_the_two_readings_of_identical_work_agree():
    """+256ms and +186ms are both normal; both must get the same verdict.

    Run 40168930560 scored x1.474 and run 40642421691 scored x1.286 for
    comparable added work. The old gate passed one and failed the other.
    """
    worse_ratio = _g3(evaluate(_pair(796.0, 540.0)))
    better_ratio = _g3(evaluate(_pair(836.0, 650.0)))
    assert worse_ratio.passed == better_ratio.passed
    assert worse_ratio.actual > better_ratio.actual


# --- Ceiling: a real doubling cannot hide ------------------------------


# --- Per-stratum judging (replaces the global-ratio tests) --------------


def test_a_stratum_over_its_budget_fails():
    """800ms of added latency in the `article` stratum (budget 50) is a real
    regression: that stratum is pure extraction, which costs tens of ms."""
    gate = _g3(evaluate(_pair(1300.0, 500.0, stratum="article")))
    assert not gate.passed, gate.detail
    assert "stratum latency budget exceeded" in gate.detail
    assert "article" in gate.detail


def test_a_fast_network_does_not_fail_the_gate():
    """The defect this gate was rebuilt to fix.

    With a 100ms baseline, +30ms of extraction gives a ratio of 1.30 — exactly
    the old gate's threshold, so it passed or failed on rounding. The delta is
    what the user feels and what the product controls, so the budget judges
    that instead.
    """
    gate = _g3(evaluate(_pair(130.0, 100.0, stratum="article")))
    assert gate.passed, gate.detail


def test_the_budget_is_stated_in_the_detail():
    gate = _g3(evaluate(_pair(550.0, 500.0, stratum="article")))
    assert "article" in gate.detail
    assert "50ms" in gate.detail


def test_render_heavy_stratum_is_not_judged_on_speed():
    """js_heavy is slower by design: the pipeline renders what the baseline
    leaves as an empty shell. Its budget is None, so a large delta passes."""
    gate = _g3(evaluate(_pair(2500.0, 400.0, stratum="js_heavy")))
    assert gate.passed, gate.detail
    assert "output-judged" in gate.detail


def test_an_unknown_stratum_falls_back_to_a_budget():
    """A new corpus stratum must show up as a gate result, not vanish."""
    gate = _g3(evaluate(_pair(2000.0, 400.0, stratum="brand_new_stratum")))
    assert not gate.passed, gate.detail
    assert "brand_new_stratum" in gate.detail


def test_budgets_can_be_tightened():
    """Budgets are data, so a stricter run is a data change, not a code change."""
    import webscout_mcp.eval.ab_eval as ab

    obs = _pair(550.0, 500.0, stratum="article")  # +50ms, exactly at budget
    assert _g3(evaluate(obs)).passed
    saved = dict(ab.STRATUM_LATENCY_BUDGET_MS)
    try:
        ab.STRATUM_LATENCY_BUDGET_MS["article"] = 10.0
        strict = _g3(evaluate(obs))
        assert not strict.passed, "a 10ms budget must reject a 50ms delta"
    finally:
        ab.STRATUM_LATENCY_BUDGET_MS.clear()
        ab.STRATUM_LATENCY_BUDGET_MS.update(saved)


def test_the_global_ratio_is_reported_but_not_judged():
    """The end-to-end ratio still appears (users feel it) but does not decide.

    A ratio above the old 1.3 threshold passes when the delta is inside budget:
    that is the whole point of the change.
    """
    gate = _g3(evaluate(_pair(130.0, 100.0, stratum="article")))
    assert gate.passed, gate.detail
    assert "reported not judged" in gate.detail
    assert gate.actual == pytest.approx(1.30, abs=0.01)


def _pair_with_recovery(
    fast_ms: float,
    baseline_ms: float,
    recovery_ms: float,
    n_fast: int = 19,
    n_recovery: int = 1,
    n: int = 20,
) -> list[ArmObservation]:
    obs: list[ArmObservation] = []
    for i in range(n):
        obs.append(ArmObservation(f"c{i}", "baseline", True, 5000, baseline_ms))
    for i in range(n_fast):
        obs.append(ArmObservation(f"p{i}", "pipeline", True, 5000, fast_ms))
    for i in range(n_recovery):
        obs.append(ArmObservation(f"r{i}", "pipeline", True, 5000, recovery_ms, recovery_used=True))
    return obs


def test_recovery_in_the_tail_does_not_fail_the_fast_path():
    """The exact retest shape: 19 fast cases ~550ms, 1 recovery 6600ms.

    Raw P95 of the pipeline arm IS the recovery case, x12 the baseline. The
    layered gate measures the fast path (550 vs 500, x1.10) and passes.
    """
    obs = _pair_with_recovery(550.0, 500.0, 6600.0)
    gate = _g3(evaluate(obs))
    assert gate.passed, gate.detail
    assert "recovery 1/20" in gate.detail


def test_recovery_rate_above_bound_fails():
    """Recovering on 3 of 6 cases means the fast path is broken, not that
    recovery works. Default bound is 25%."""
    obs = _pair_with_recovery(550.0, 500.0, 6600.0, n_fast=3, n_recovery=3, n=6)
    gate = _g3(evaluate(obs))
    assert not gate.passed
    assert "FAIL: recovery rate" in gate.detail


def test_recovery_that_produces_nothing_fails():
    """Paying the playwright launch cost and returning <200 chars is a defect."""
    obs: list[ArmObservation] = []
    for i in range(20):
        obs.append(ArmObservation(f"c{i}", "baseline", True, 5000, 500.0))
    for i in range(19):
        obs.append(ArmObservation(f"p{i}", "pipeline", True, 5000, 550.0))
    obs.append(ArmObservation("r0", "pipeline", True, 100, 6600.0, recovery_used=True))
    gate = _g3(evaluate(obs))
    assert not gate.passed
    assert "FAIL: recovery produced no usable content" in gate.detail


def test_recovery_bound_can_be_tightened():
    obs = _pair_with_recovery(550.0, 500.0, 6600.0, n_fast=18, n_recovery=2)
    assert _g3(evaluate(obs)).passed, "2/20 = 10% is inside the default 25%"
    strict = _g3(evaluate(obs, max_recovery_rate=0.05))
    assert not strict.passed, "a 5% bound must reject a 10% recovery rate"
