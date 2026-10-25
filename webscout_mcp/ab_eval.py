"""A/B evaluation harness: production pipeline vs a bare baseline.

This module exists because of a specific failure in this project's history.
On 2026-10-23 an A/B run produced the numbers that every quality claim still
cites - a 7.3pp content-usability deficit, P95 14933ms vs 11625ms, search
latency +51.7% - and the harness that produced them was never committed. It
lived in a local ``.ab-eval/`` directory, was run once, and was gone. When it
came time to check whether v1.9.1 had fixed the deficit, re-running was
impossible: ``git log --all --diff-filter=A -- "*ab_eval*"`` returns nothing.

So the rule this module enforces is: **an evaluation that decides something must
be reproducible from the repository alone**. Two consequences shape the design.

1. The comparison is a function, not a script that happened to be run. Both arms
   are pure computations over the same observations, so the scoring logic is
   testable without any network at all.

2. The two arms are defined mechanically, not by "production vs whatever we had
   before":

   - ``pipeline`` is what WebScout actually returns to a caller: extraction,
     truncation to the output limit, browser/fallback recovery. Judged on the
     content the caller receives.
   - ``baseline`` is the naive approach an agent would otherwise take: one HTTP
     GET, no extraction, no recovery, no escalation. Judged on what that yields.

   A pipeline that loses content relative to the naive approach is not earning
   its keep, which is exactly the regression the original run found.

Latency is reported as directional only. The historical comparison mixed a
task-level denominator with a per-operation one, which made the latency delta
not strictly comparable. This harness records both denominators explicitly and
refuses to present a single headline latency ratio.

Nothing here touches the network. Callers supply observations; see
``scripts/ab_evaluate.py`` for the runner that produces them.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# A fetched body shorter than this is not usable as evidence for an agent.
# Must stay in step with observability.THIN_CONTENT_CHARS: when these two drift,
# the A/B verdict and the SLO report disagree about the same request.
USABLE_CONTENT_CHARS = 200


@dataclass(frozen=True)
class ArmObservation:
    """One case evaluated under one arm.

    Each field is deliberately a plain scalar so an observation can be
    serialised, diffed and reasoned about without the harness running.
    """

    case_id: str
    arm: str  # "pipeline" | "baseline"
    ok: bool
    """Did the arm produce a response at all (no exception/timeout)."""

    returned_chars: int
    """Characters the caller actually receives from this arm."""

    latency_ms: float

    pre_limit_chars: int | None = None
    """Characters available before WebScout's own output limit cut them.
    None for the baseline arm, which has no output limit."""

    escaped_error: str | None = None
    """Set when the arm raised. Kept as the exception type, never a message
    (messages can carry URLs)."""

    def usable(self, threshold: int = USABLE_CONTENT_CHARS) -> bool:
        return self.ok and self.returned_chars >= threshold


@dataclass
class ArmSummary:
    arm: str
    cases: int
    ok: int
    usable: int
    truncated: int
    total_chars: int
    errors: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)

    @property
    def usable_rate(self) -> float:
        """Usable cases over ALL attempted cases, not just successes.

        Dividing by successes would hide exactly the failure that matters: a
        pipeline that drops requests can look better than one that answers
        them all with slightly thinner content.
        """
        if self.cases == 0:
            return 0.0
        return self.usable / self.cases

    @property
    def error_rate(self) -> float:
        if self.cases == 0:
            return 0.0
        return (self.cases - self.ok) / self.cases

    def percentile(self, p: float) -> float:
        if not self.latencies:
            return 0.0
        s = sorted(self.latencies)
        k = max(0, min(len(s) - 1, round(p * (len(s) - 1))))
        return s[k]

    @property
    def p50_ms(self) -> float:
        return self.percentile(0.50)

    @property
    def p95_ms(self) -> float:
        return self.percentile(0.95)

    @property
    def latency_denominator(self) -> str:
        """Which denominator the latency numbers use.

        The historical A/B mixed these, so each summary states its own.
        """
        return "per-attempt" if self.cases == len(self.latencies) else "per-success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "cases": self.cases,
            "ok": self.ok,
            "usable": self.usable,
            "usable_rate": round(self.usable_rate, 4),
            "truncated": self.truncated,
            "error_rate": round(self.error_rate, 4),
            "errors": dict(self.errors),
            "total_chars": self.total_chars,
            "mean_chars": round(self.total_chars / self.cases, 1) if self.cases else 0.0,
            "p50_ms": round(self.p50_ms, 1),
            "p95_ms": round(self.p95_ms, 1),
            "latency_denominator": self.latency_denominator,
        }


def summarize(
    observations: Sequence[ArmObservation],
    arm: str,
    *,
    threshold_chars: int = USABLE_CONTENT_CHARS,
) -> ArmSummary:
    """Aggregate one arm's observations. Pure function; no I/O."""
    rows = [o for o in observations if o.arm == arm]
    summary = ArmSummary(
        arm=arm,
        cases=len(rows),
        ok=0,
        usable=0,
        truncated=0,
        total_chars=0,
    )
    for o in rows:
        if o.ok:
            summary.ok += 1
            summary.latencies.append(float(o.latency_ms))
        else:
            key = o.escaped_error or "unknown"
            summary.errors[key] = summary.errors.get(key, 0) + 1
        if o.usable(threshold_chars):
            summary.usable += 1
        if o.pre_limit_chars is not None and o.pre_limit_chars > o.returned_chars:
            summary.truncated += 1
        summary.total_chars += max(0, o.returned_chars)
    return summary


@dataclass(frozen=True)
class GateVerdict:
    """One pass/fail decision, with the numbers that produced it."""

    name: str
    passed: bool
    actual: float | None
    threshold: float | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "actual": self.actual,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass
class ABResult:
    pipeline: ArmSummary
    baseline: ArmSummary
    gates: list[GateVerdict]
    case_count: int
    corpus_sha: str
    threshold_chars: int
    advisories: list[str] = field(default_factory=list)
    """Non-gating observations worth reading but which must not fail the run.

    The clearest case: the gates are purely relative, so two arms at 0% usable
    content compare equal and the A/B passes. That is correct - the comparison
    answers "does the pipeline earn its keep", while the absolute floor is the
    SLO's job (Usable Content Rate >= 85%). But a PASS should never be read as
    "quality is fine" when both arms returned nothing, so it is called out.
    """

    @property
    def passed(self) -> bool:
        return all(g.passed for g in self.gates)

    @property
    def usable_rate_delta_pp(self) -> float:
        """Pipeline minus baseline, in percentage points.

        Positive means WebScout returns usable content more often than the
        naive approach. The 2026-10-23 run measured -7.3pp here.
        """
        return (self.pipeline.usable_rate - self.baseline.usable_rate) * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_count": self.case_count,
            "corpus_sha": self.corpus_sha,
            "threshold_chars": self.threshold_chars,
            "passed": self.passed,
            "usable_rate_delta_pp": round(self.usable_rate_delta_pp, 2),
            "pipeline": self.pipeline.to_dict(),
            "baseline": self.baseline.to_dict(),
            "gates": [g.to_dict() for g in self.gates],
            "advisories": list(self.advisories),
            "latency_note": (
                "Directional only. The two arms have different denominators "
                "and different work scopes; see latency_denominator per arm."
            ),
        }


def evaluate(
    observations: Iterable[ArmObservation],
    *,
    corpus_sha: str = "",
    threshold_chars: int = USABLE_CONTENT_CHARS,
    min_usable_rate_delta_pp: float = 0.0,
    max_p95_ratio: float = 1.30,
) -> ABResult:
    """Score both arms and apply the quality gates.

    Gate semantics, and why only these three:

    G1 usable-rate must not lose ground
        The pipeline must return usable content at least as often as the naive
        approach. Threshold 0.0pp rather than "beat it by X": the contract is
        "do not make things worse", which is what the layer promises.

    G2 error rate must not rise
        A pipeline that is thrifty with content but drops requests is worse
        than one that answers thinly. Same 0.0pp logic.

    G3 p95 latency must stay within a ratio
        Directional. The arms do different work, so this catches gross
        regressions only, not small ones. Ratio rather than absolute ms so the
        gate survives a slower or faster machine.
    """
    obs = list(observations)
    pipeline = summarize(obs, "pipeline", threshold_chars=threshold_chars)
    baseline = summarize(obs, "baseline", threshold_chars=threshold_chars)

    case_count = len({o.case_id for o in obs})
    gates: list[GateVerdict] = []

    delta_pp = (pipeline.usable_rate - baseline.usable_rate) * 100.0
    gates.append(
        GateVerdict(
            name="G1_usable_rate_not_worse",
            passed=delta_pp >= min_usable_rate_delta_pp,
            actual=round(delta_pp, 2),
            threshold=min_usable_rate_delta_pp,
            detail=(f"pipeline {pipeline.usable_rate:.1%} vs baseline {baseline.usable_rate:.1%} ({delta_pp:+.2f}pp)"),
        )
    )

    err_delta = (pipeline.error_rate - baseline.error_rate) * 100.0
    gates.append(
        GateVerdict(
            name="G2_error_rate_not_worse",
            passed=err_delta <= 0.0,
            actual=round(err_delta, 2),
            threshold=0.0,
            detail=(f"pipeline {pipeline.error_rate:.1%} vs baseline {baseline.error_rate:.1%} ({err_delta:+.2f}pp)"),
        )
    )

    # Compare p95 only when both arms have samples; an empty arm means the
    # comparison is not meaningful and the gate must not silently pass.
    if pipeline.latencies and baseline.latencies and baseline.p95_ms > 0:
        ratio = pipeline.p95_ms / baseline.p95_ms
        gates.append(
            GateVerdict(
                name="G3_p95_latency_ratio",
                passed=ratio <= max_p95_ratio,
                actual=round(ratio, 3),
                threshold=max_p95_ratio,
                detail=(f"pipeline P95 {pipeline.p95_ms:.0f}ms vs baseline {baseline.p95_ms:.0f}ms (x{ratio:.2f})"),
            )
        )
    else:
        gates.append(
            GateVerdict(
                name="G3_p95_latency_ratio",
                passed=False,
                actual=None,
                threshold=max_p95_ratio,
                detail="insufficient latency samples in one or both arms",
            )
        )

    advisories: list[str] = []
    if case_count > 0 and pipeline.usable == 0 and baseline.usable == 0:
        advisories.append(
            "Both arms returned no usable content. The gates compare the pipeline "
            "against the baseline, so they cannot fail here, but this is not a "
            "statement that quality is acceptable - check the SLO usable-content "
            "rate separately."
        )
    if pipeline.cases == 0 or baseline.cases == 0:
        advisories.append(
            "One arm recorded no observations. The comparison is not meaningful; treat any PASS as unearned."
        )

    return ABResult(
        pipeline=pipeline,
        baseline=baseline,
        gates=gates,
        case_count=case_count,
        corpus_sha=corpus_sha,
        threshold_chars=threshold_chars,
        advisories=advisories,
    )


def corpus_fingerprint(paths: Sequence[str | Path]) -> str:
    """Stable hash of the corpora used, so a report names its own inputs.

    A result without this cannot be reproduced even with the harness committed,
    because you would not know which corpus produced it.
    """
    h = hashlib.sha256()
    for p in paths:
        raw = Path(p).read_text(encoding="utf-8")
        data = json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=True)
        h.update(data.encode("utf-8"))
    return h.hexdigest()[:16]


def observations_to_jsonl(observations: Iterable[ArmObservation]) -> str:
    """Serialise every observation so a report can be re-scored later.

    This is the piece the original harness lacked: it kept the verdict and threw
    away the evidence. With observations committed, changing a threshold does
    not require re-running the network.
    """
    lines = []
    for o in observations:
        lines.append(
            json.dumps(
                {
                    "case_id": o.case_id,
                    "arm": o.arm,
                    "ok": o.ok,
                    "returned_chars": o.returned_chars,
                    "latency_ms": round(float(o.latency_ms), 2),
                    "pre_limit_chars": o.pre_limit_chars,
                    "escaped_error": o.escaped_error,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return "\n".join(lines) + "\n"


def observations_from_jsonl(text: str) -> list[ArmObservation]:
    out: list[ArmObservation] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        out.append(
            ArmObservation(
                case_id=d["case_id"],
                arm=d["arm"],
                ok=bool(d["ok"]),
                returned_chars=int(d["returned_chars"]),
                latency_ms=float(d["latency_ms"]),
                pre_limit_chars=d.get("pre_limit_chars"),
                escaped_error=d.get("escaped_error"),
            )
        )
    return out


def render_markdown(result: ABResult) -> str:
    """Human-readable report. Leads with the verdict, then the numbers."""
    verdict = "PASS" if result.passed else "FAIL"
    lines = [
        f"# A/B Evaluation — {verdict}",
        "",
        f"- cases: {result.case_count}",
        f"- corpus fingerprint: `{result.corpus_sha}`",
        f"- usable threshold: {result.threshold_chars} chars",
        f"- usable-rate delta: **{result.usable_rate_delta_pp:+.2f}pp**",
        "",
        "## Gates",
        "",
        "| Gate | Result | Actual | Threshold | Detail |",
        "|---|---|---|---|---|",
    ]
    for g in result.gates:
        actual = "n/a" if g.actual is None else f"{g.actual}"
        lines.append(f"| {g.name} | {'PASS' if g.passed else 'FAIL'} | {actual} | {g.threshold} | {g.detail} |")

    lines += ["", "## Arms", ""]
    lines.append("| Metric | pipeline | baseline |")
    lines.append("|---|---|---|")
    p, b = result.pipeline.to_dict(), result.baseline.to_dict()
    for key in ("cases", "ok", "usable", "usable_rate", "error_rate", "truncated", "mean_chars", "p50_ms", "p95_ms"):
        lines.append(f"| {key} | {p[key]} | {b[key]} |")

    lines += [
        "",
        (
            "> Latency is directional only: the arms differ in both work scope and "
            "denominator. Per-arm `latency_denominator` is recorded above."
        ),
    ]
    if result.advisories:
        lines += ["", "## Advisories", ""]
        lines += [f"- {a}" for a in result.advisories]
    return "\n".join(lines) + "\n"


def median(values: Sequence[float]) -> float:
    """Median with an empty-sequence guard. Exposed for report helpers."""
    return statistics.median(values) if values else 0.0
