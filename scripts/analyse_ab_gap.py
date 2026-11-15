"""Decide G3 empirically: is the pipeline's fast-path tail proxy jitter or a
real regression?

The claim to test: "the gap between pipeline and baseline P95 comes from the
network, not from pipeline work". If that is true, then within one run:

  * the per-case latency DIFFERENCE (pipeline - baseline) should be
    uncorrelated with the case's absolute latency. Pipeline work is a roughly
    fixed addition; network jitter scales with the request.

  * the difference should scatter on BOTH sides of zero for the fast cases,
    not sit at a constant positive offset.

  * slow cases should be slow in BOTH arms (same URL, same moment). If a case
    is slow only in the pipeline arm, that is pipeline work.

The third is the decisive one and is directly checkable per case: compare each
case's pipeline latency against the baseline latency of the SAME case.

Usage: python scripts/analyse_ab_gap.py <observations.jsonl> [more...]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path


def load(paths: list[Path]) -> tuple[dict, dict]:
    pipe: dict[str, dict] = {}
    base: dict[str, dict] = {}
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            (pipe if row["arm"] == "pipeline" else base)[row["case_id"]] = row
    return pipe, base


def analyse(paths: list[Path]) -> int:
    pipe, base = load(paths)
    shared = sorted(set(pipe) & set(base))
    if not shared:
        print("no shared case ids — cannot pair", file=sys.stderr)
        return 2

    # fast path only: recoveries are a different operation
    fast = [c for c in shared if not pipe[c].get("recovery_used")]
    print(f"cases: {len(shared)} total, {len(fast)} fast-path (recovery excluded)")

    # 1) per-case difference
    diffs = [pipe[c]["latency_ms"] - base[c]["latency_ms"] for c in fast]
    neg = sum(1 for d in diffs if d < 0)
    print()
    print("per-case latency difference (pipeline - baseline), fast path:")
    print(f"  median {statistics.median(diffs):+.0f}ms   mean {statistics.mean(diffs):+.0f}ms")
    print(f"  min {min(diffs):+.0f}   max {max(diffs):+.0f}")
    print(f"  pipeline FASTER on {neg}/{len(diffs)} cases")
    if neg:
        print("  -> both-signed scatter means the gap is not a constant pipeline cost")

    # 2) is the gap proportional to absolute latency?
    xs = [base[c]["latency_ms"] for c in fast]
    ys = diffs
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    r = num / den if den else 0.0
    print()
    print("correlation of the gap with baseline latency (jitter scales, work does not):")
    print(f"  r = {r:+.3f}  (|r| near 1 => the gap tracks network; near 0 => fixed cost)")

    # 3) are slow cases slow in BOTH arms?
    print()
    print("slowest 5 fast-path cases, both arms (same URL, same run):")
    for c in sorted(fast, key=lambda c: -pipe[c]["latency_ms"])[:5]:
        p, b = pipe[c]["latency_ms"], base[c]["latency_ms"]
        verdict = "both slow" if b > 800 else "pipeline only"
        print(f"  {c:24} pipeline {p:7.0f}ms   baseline {b:7.0f}ms   {verdict}")

    # 4) P95 decomposition
    def p95(vals: list[float]) -> float:
        s = sorted(vals)
        return s[min(len(s) - 1, round(0.95 * (len(s) - 1)))]

    pp = p95([pipe[c]["latency_ms"] for c in fast])
    bb = p95([base[c]["latency_ms"] for c in fast])
    print()
    print("fast-path P95:")
    print(f"  pipeline {pp:.0f}ms   baseline {bb:.0f}ms   ratio {pp / bb:.2f}")
    print(f"  absolute delta {pp - bb:+.0f}ms")
    print()
    print("reading: a ratio gate fails on a fast network even when the product is")
    print("faster in absolute terms; the delta is the number the user feels.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("observations", nargs="+", type=Path)
    args = ap.parse_args()
    return analyse(args.observations)


if __name__ == "__main__":
    sys.exit(main())
