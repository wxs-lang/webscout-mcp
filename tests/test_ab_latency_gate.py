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


def _pair(pipeline_ms: float, baseline_ms: float, n: int = 20) -> list[ArmObservation]:
    obs: list[ArmObservation] = []
    for i in range(n):
        obs.append(ArmObservation(f"c{i}", "pipeline", True, 5000, pipeline_ms))
        obs.append(ArmObservation(f"c{i}", "baseline", True, 5000, baseline_ms))
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


def test_overhead_on_a_slow_network_passes():
    """Measured pair from run 40168930560: 796 vs 540ms, x1.474, delta +256ms.

    The ratio is above 1.30, so the old gate failed this run. The pipeline did
    the same work it does every run; the network was simply fast that minute.
    """
    gate = _g3(evaluate(_pair(796.0, 540.0)))
    assert gate.passed, gate.detail
    assert gate.actual == pytest.approx(1.474, abs=0.01)


def test_ratio_just_over_the_bound_still_passes_on_delta():
    """x1.474 with +256ms is the worst non-failing shape observed."""
    gate = _g3(evaluate(_pair(796.0, 540.0)))
    assert gate.passed, gate.detail


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


def test_tripling_on_a_small_baseline_fails():
    """300 vs 100 is x3.00 with only +200ms delta.

    Without a ratio ceiling the delta exemption would wave this through, which a
    test caught before this shipped.
    """
    gate = _g3(evaluate(_pair(300.0, 100.0)))
    assert not gate.passed, gate.detail
    assert gate.actual == pytest.approx(3.0, abs=0.01)


def test_ratio_above_ceiling_fails_even_with_small_delta():
    """250 vs 100: x2.50, delta +150ms. Delta is modest; the ratio is not."""
    gate = _g3(evaluate(_pair(250.0, 100.0)))
    assert not gate.passed


def test_delta_over_the_bound_fails():
    """The one genuine historical failure: x1.63 and +337ms."""
    gate = _g3(evaluate(_pair(870.0, 533.0)))
    assert not gate.passed, gate.detail


def test_large_absolute_slowdown_fails():
    """4000 vs 1000: x4.00 and +3000ms. Fails on both counts."""
    assert not _g3(evaluate(_pair(4000.0, 1000.0))).passed


# --- Sampling guard ---------------------------------------------------


def test_no_latency_samples_fails_rather_than_passing_silently():
    obs = [ArmObservation(f"c{i}", "pipeline", False, 0, 0.0, escaped_error="TimeoutError") for i in range(3)]
    obs += [ArmObservation(f"c{i}", "baseline", False, 0, 0.0, escaped_error="TimeoutError") for i in range(3)]
    gate = _g3(evaluate(obs))
    assert not gate.passed
    assert gate.actual is None


def test_detail_explains_both_conditions():
    """A failing gate must say why, not just that it failed."""
    gate = _g3(evaluate(_pair(300.0, 100.0)))
    assert "ratio <=" in gate.detail
    assert "delta <=" in gate.detail


# --- Thresholds are configurable --------------------------------------


def test_ceiling_and_delta_can_be_tightened():
    obs = _pair(796.0, 540.0)  # x1.474 with +256ms: passes by default
    assert _g3(evaluate(obs)).passed
    strict = _g3(evaluate(obs, max_p95_ratio_ceiling=1.4))
    assert not strict.passed, "a 1.4 ceiling must reject a x1.474 ratio"


def test_delta_bound_can_be_tightened():
    obs = _pair(796.0, 540.0)  # +256ms delta
    assert _g3(evaluate(obs)).passed
    strict = _g3(evaluate(obs, max_p95_delta_ms=200.0))
    assert not strict.passed, "a 256ms delta must fail a 200ms bound"


# --- Layered form: recovery must not read as a latency regression ------
# The 2026-11-13 retest failed the old raw-P95 gate at x3.12 while every
# recovery succeeded; whether a 3-7s playwright launch lands in the 95th
# percentile is a property of the corpus, not the code.


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


def test_zero_recoveries_apply_the_plain_rule():
    """No recovery cases -> gate reduces to the historical ratio/delta rule."""
    obs = _pair(796.0, 540.0)  # x1.474 +256ms: the old pass-by-delta shape
    gate = _g3(evaluate(obs))
    assert gate.passed, gate.detail
    assert "recovery" not in gate.detail


def test_recovery_bound_can_be_tightened():
    obs = _pair_with_recovery(550.0, 500.0, 6600.0, n_fast=18, n_recovery=2)
    assert _g3(evaluate(obs)).passed, "2/20 = 10% is inside the default 25%"
    strict = _g3(evaluate(obs, max_recovery_rate=0.05))
    assert not strict.passed, "a 5% bound must reject a 10% recovery rate"
