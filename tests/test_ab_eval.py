"""Tests for the committed A/B evaluation harness.

The point of these tests is not that scoring arithmetic works - it is that the
measurement is *reproducible from the repository*.

The 2026-10-23 run that produced every quality number this project cites (the
-7.3pp usable-content deficit, P95 14933ms vs 11625ms) used a harness in an
uncommitted .ab-eval/ directory. It ran once and was lost, so nobody can check
whether the deficit was ever fixed. These tests exist so that cannot happen
again: the scoring is a pure function, the evidence is serialisable, and a
recorded run can be re-scored without touching the network.
"""

from __future__ import annotations

import json

import pytest

from webscout_mcp.ab_eval import (
    USABLE_CONTENT_CHARS,
    ArmObservation,
    corpus_fingerprint,
    evaluate,
    observations_from_jsonl,
    observations_to_jsonl,
    render_markdown,
    summarize,
)


def _arm_pair(
    n: int,
    pipeline_usable: int,
    baseline_usable: int,
    *,
    pipeline_ms: float = 120.0,
    baseline_ms: float = 100.0,
    pipeline_chars: int = 5000,
    baseline_chars: int = 5000,
) -> list[ArmObservation]:
    obs: list[ArmObservation] = []
    for i in range(n):
        obs.append(
            ArmObservation(
                case_id=f"c{i}",
                arm="pipeline",
                ok=True,
                returned_chars=pipeline_chars if i < pipeline_usable else 50,
                latency_ms=pipeline_ms,
            )
        )
        obs.append(
            ArmObservation(
                case_id=f"c{i}",
                arm="baseline",
                ok=True,
                returned_chars=baseline_chars if i < baseline_usable else 50,
                latency_ms=baseline_ms,
            )
        )
    return obs


# --- The historical regression must be detectable -------------------------


def test_reproduces_the_historic_minus_7pp_deficit_as_a_failure():
    """The exact shape of the 2026-10-23 finding: 84% vs 91% usable.

    Scored with zero tolerance: seven cases behind is far beyond any allowance
    for flakiness, so this must fail however the tolerance is set.
    """
    result = evaluate(_arm_pair(100, pipeline_usable=84, baseline_usable=91), case_tolerance=0)
    assert result.usable_rate_delta_pp == pytest.approx(-7.0, abs=0.01)
    assert not result.passed
    gate = next(g for g in result.gates if g.name == "G1_usable_rate_not_worse")
    assert not gate.passed


def test_deficit_beyond_tolerance_fails_even_with_slack():
    """A 7-case gap is real, not flakiness, and must survive the tolerance."""
    result = evaluate(_arm_pair(100, pipeline_usable=84, baseline_usable=91), case_tolerance=1)
    assert not result.passed


# --- Case tolerance: a single flaky request must not flip the verdict -----


def test_one_case_behind_passes_with_default_tolerance():
    """A live CI run measured exactly this: one URL failed transiently.

    The pipeline recorded 0 chars after a 16.9s browser attempt while the same
    URL returned 1168 chars to the baseline. Across the other 39 cases the arms
    were identical. A gate that fails on that teaches people to ignore it.
    """
    obs = _arm_pair(40, pipeline_usable=39, baseline_usable=40)
    assert evaluate(obs, case_tolerance=1).passed
    assert not evaluate(obs, case_tolerance=0).passed


def test_tolerance_is_expressed_in_cases_not_percentage_points():
    """The gate reports a case gap, so boundaries cannot break on rounding.

    With 40 cases one case is exactly 2.5pp; a pp comparison of -2.5 against
    -2.5 is a float-boundary trap. The gate compares integers instead.
    """
    obs = _arm_pair(40, pipeline_usable=39, baseline_usable=40)
    gate = next(g for g in evaluate(obs, case_tolerance=1).gates if g.name == "G1_usable_rate_not_worse")
    assert gate.actual == 1
    assert gate.threshold == 1
    assert "1 case(s) behind" in gate.detail


def test_tolerance_does_not_mask_larger_gaps():
    obs = _arm_pair(40, pipeline_usable=37, baseline_usable=40)
    assert not evaluate(obs, case_tolerance=1).passed


def test_zero_tolerance_restores_strict_comparison():
    obs = _arm_pair(40, pipeline_usable=39, baseline_usable=40)
    assert not evaluate(obs, case_tolerance=0).passed


def test_tolerance_also_applies_to_the_error_gate():
    obs = _arm_pair(20, pipeline_usable=20, baseline_usable=20)
    obs.append(ArmObservation("x0", "pipeline", False, 0, 100.0, escaped_error="TimeoutError"))
    assert evaluate(obs, case_tolerance=1).passed
    assert not evaluate(obs, case_tolerance=0).passed


def test_tolerance_is_recorded_in_the_report():
    """A passing run must still show how much slack it used."""
    obs = _arm_pair(40, pipeline_usable=39, baseline_usable=40)
    payload = evaluate(obs, case_tolerance=2).to_dict()
    gate = next(g for g in payload["gates"] if g["name"] == "G1_usable_rate_not_worse")
    assert gate["threshold"] == 2


def test_equal_arms_pass():
    result = evaluate(_arm_pair(50, pipeline_usable=50, baseline_usable=50))
    assert result.usable_rate_delta_pp == 0.0
    assert result.passed


def test_pipeline_better_than_baseline_passes():
    result = evaluate(_arm_pair(100, pipeline_usable=95, baseline_usable=60))
    assert result.usable_rate_delta_pp == pytest.approx(35.0, abs=0.01)
    assert result.passed


# --- Denominators: the trap that made the old numbers incomparable --------


def test_usable_rate_divides_by_all_cases_not_by_successes():
    """A pipeline that drops requests must not look good on rate."""
    obs = [
        # 5 cases; pipeline answers 2 of them, both usable.
        ArmObservation("c0", "pipeline", True, 5000, 100.0),
        ArmObservation("c1", "pipeline", True, 5000, 100.0),
        ArmObservation("c2", "pipeline", False, 0, 100.0, escaped_error="TimeoutError"),
        ArmObservation("c3", "pipeline", False, 0, 100.0, escaped_error="TimeoutError"),
        ArmObservation("c4", "pipeline", False, 0, 100.0, escaped_error="TimeoutError"),
    ]
    s = summarize(obs, "pipeline")
    assert s.cases == 5
    assert s.ok == 2
    assert s.usable == 2
    # 2/5, not 2/2.
    assert s.usable_rate == pytest.approx(0.4)
    assert s.error_rate == pytest.approx(0.6)


def test_dropping_requests_fails_the_error_gate():
    obs = _arm_pair(10, pipeline_usable=10, baseline_usable=10)
    obs += [ArmObservation(f"extra{i}", "pipeline", False, 0, 100.0, escaped_error="TimeoutError") for i in range(5)]
    result = evaluate(obs)
    gate = next(g for g in result.gates if g.name == "G2_error_rate_not_worse")
    assert not gate.passed
    assert not result.passed


# --- Latency gating -------------------------------------------------------


def test_latency_ratio_gate_catches_gross_regression():
    result = evaluate(_arm_pair(20, 20, 20, pipeline_ms=300.0, baseline_ms=100.0))
    gate = next(g for g in result.gates if g.name == "G3_p95_latency_ratio")
    assert not gate.passed
    assert result.passed is False


def test_latency_gate_passes_within_ratio():
    result = evaluate(_arm_pair(20, 20, 20, pipeline_ms=110.0, baseline_ms=100.0))
    gate = next(g for g in result.gates if g.name == "G3_p95_latency_ratio")
    assert gate.passed


def test_missing_latency_samples_fail_the_gate_rather_than_passing_silently():
    """An empty arm is "not comparable", never "fine"."""
    obs = [ArmObservation(f"c{i}", "pipeline", False, 0, 0.0, escaped_error="TimeoutError") for i in range(3)]
    obs += [ArmObservation(f"c{i}", "baseline", False, 0, 0.0, escaped_error="TimeoutError") for i in range(3)]
    result = evaluate(obs)
    gate = next(g for g in result.gates if g.name == "G3_p95_latency_ratio")
    assert not gate.passed
    assert gate.actual is None


def test_summary_states_which_latency_denominator_it_used():
    """The old comparison mixed task-level and per-operation denominators."""
    ok_only = [ArmObservation(f"c{i}", "pipeline", True, 5000, 100.0) for i in range(3)]
    assert summarize(ok_only, "pipeline").latency_denominator == "per-attempt"


# --- Usable threshold ----------------------------------------------------


def test_threshold_boundary():
    at = ArmObservation("a", "pipeline", True, USABLE_CONTENT_CHARS, 10.0)
    below = ArmObservation("b", "pipeline", True, USABLE_CONTENT_CHARS - 1, 10.0)
    assert at.usable()
    assert not below.usable()


def test_failed_arm_is_never_usable_even_with_content():
    o = ArmObservation("a", "pipeline", False, 99999, 10.0, escaped_error="TimeoutError")
    assert not o.usable()


def test_custom_threshold_is_honoured():
    result = evaluate(_arm_pair(10, 10, 10, pipeline_chars=500, baseline_chars=500), threshold_chars=1000)
    assert result.threshold_chars == 1000
    assert result.pipeline.usable == 0


# --- Truncation accounting ----------------------------------------------


def test_truncation_counts_only_when_the_limit_actually_cut():
    obs = [
        ArmObservation("a", "pipeline", True, 8000, 10.0, pre_limit_chars=200000),
        ArmObservation("b", "pipeline", True, 8000, 10.0, pre_limit_chars=8000),
        ArmObservation("c", "pipeline", True, 500, 10.0, pre_limit_chars=None),
    ]
    s = summarize(obs, "pipeline")
    assert s.truncated == 1


# --- Reproducibility: the whole point -----------------------------------


def test_observations_roundtrip_through_jsonl():
    obs = _arm_pair(5, 4, 3)
    text = observations_to_jsonl(obs)
    back = observations_from_jsonl(text)
    assert len(back) == len(obs)
    assert back[0] == obs[0]
    # And the re-scored verdict must be identical.
    assert evaluate(back).to_dict() == evaluate(obs).to_dict()


def test_recorded_observations_can_be_rescored_after_a_threshold_change():
    """No network needed to re-check a verdict - this is what was missing.

    A threshold change moves the per-arm usable counts. Because both arms are
    scored with the same threshold, the *delta* between them is unchanged: the
    A/B answers "does the pipeline beat the naive approach", which does not
    depend on where the bar sits. What the threshold does change is the absolute
    usable counts the report publishes, and those must track it.
    """
    obs = _arm_pair(10, 10, 10, pipeline_chars=500, baseline_chars=500)
    text = observations_to_jsonl(obs)

    strict = evaluate(observations_from_jsonl(text), threshold_chars=1000)
    loose = evaluate(observations_from_jsonl(text), threshold_chars=100)

    # Same relative verdict, because the arms move together.
    assert strict.usable_rate_delta_pp == loose.usable_rate_delta_pp == 0.0

    # But the absolute counts follow the threshold.
    assert strict.threshold_chars == 1000
    assert strict.pipeline.usable == 0
    assert loose.threshold_chars == 100
    assert loose.pipeline.usable == 10


def test_both_arms_empty_still_passes_but_says_so():
    """The gates are relative, so equal-and-empty passes. That needs saying.

    A PASS must not be read as "quality is fine" when neither arm returned
    anything; the absolute floor belongs to the SLO, not to this comparison.
    """
    result = evaluate(_arm_pair(10, 0, 0))
    assert result.passed, "relative comparison of two equal arms"
    assert result.advisories, "but the emptiness must be called out"
    assert any("no usable content" in a for a in result.advisories)
    assert "Advisories" in render_markdown(result)
    assert result.to_dict()["advisories"]


def test_missing_arm_triggers_an_advisory():
    obs = [ArmObservation(f"c{i}", "pipeline", True, 5000, 100.0) for i in range(3)]
    result = evaluate(obs)
    assert any("no observations" in a for a in result.advisories)


def test_jsonl_never_contains_content_or_urls():
    """The evidence file gets committed, so it must stay scalar-only."""
    obs = [
        ArmObservation("c0", "pipeline", True, 5000, 10.0, pre_limit_chars=9000),
        ArmObservation("c0", "baseline", False, 0, 10.0, escaped_error="TimeoutError"),
    ]
    text = observations_to_jsonl(obs)
    for forbidden in ("http://", "https://", "<html", "title", "body"):
        assert forbidden not in text
    parsed = json.loads(text.splitlines()[0])
    assert set(parsed) == {
        "case_id",
        "arm",
        "ok",
        "returned_chars",
        "latency_ms",
        "pre_limit_chars",
        "escaped_error",
    }


def test_corpus_fingerprint_is_stable_and_sensitive(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"urls": [{"url": "https://example.com/x"}]}), encoding="utf-8")
    fp1 = corpus_fingerprint([a])
    fp2 = corpus_fingerprint([a])
    assert fp1 == fp2, "same input must give the same fingerprint"

    b = tmp_path / "b.json"
    b.write_text(json.dumps({"urls": [{"url": "https://example.com/y"}]}), encoding="utf-8")
    assert corpus_fingerprint([b]) != fp1, "different corpus must give a different fingerprint"


def test_report_names_its_own_inputs():
    """A verdict without its corpus hash cannot be reproduced."""
    result = evaluate(_arm_pair(5, 5, 5), corpus_sha="abc123")
    md = render_markdown(result)
    assert "abc123" in md
    assert result.to_dict()["corpus_sha"] == "abc123"


def test_markdown_report_states_the_passed_verdict():
    ok = render_markdown(evaluate(_arm_pair(5, 5, 5)))
    bad = render_markdown(evaluate(_arm_pair(100, 84, 91)))
    assert "PASS" in ok.splitlines()[0]
    assert "FAIL" in bad.splitlines()[0]


def test_evaluate_is_deterministic():
    obs = _arm_pair(30, 25, 20, pipeline_ms=115.0, baseline_ms=100.0)
    first = evaluate(obs).to_dict()
    second = evaluate(obs).to_dict()
    assert first == second


def test_empty_observations_do_not_crash():
    result = evaluate([])
    assert result.case_count == 0
    assert result.pipeline.usable_rate == 0.0
    assert result.baseline.usable_rate == 0.0
