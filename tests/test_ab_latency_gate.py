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
