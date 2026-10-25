#!/usr/bin/env python3
"""Run the A/B evaluation: production pipeline vs a bare baseline.

Committed on purpose. The previous harness for this measurement lived in an
uncommitted ``.ab-eval/`` directory, was run once on 2026-10-23, and was then
lost - so its conclusions could never be checked again. This file is the
answer to that: the whole measurement is one command from a clean checkout.

Two modes, and both matter:

    --replay PATH   Re-score a previously recorded observations JSONL.
                    No network. Deterministic. Use this to re-check a verdict
                    after changing a threshold, or to verify the harness itself.

    (default)       Record a live run against the corpus, then score it.
                    Writes the observations next to the report, so the raw
                    evidence survives alongside the conclusion.

The live arm definitions are mechanical:

    pipeline  FetchService.fetch() - extraction, output limit, browser and
              fallback recovery. What the MCP tool actually returns.
    baseline  One plain HTTP GET through the same provider, no extraction, no
              recovery, no escalation. The naive thing an agent would do.

Both arms hit the same URL with the same client stack, so the comparison is
about the pipeline's value-add, not about network luck.

Usage:
    python scripts/ab_evaluate.py --replay path/to/observations.jsonl
    python scripts/ab_evaluate.py --limit 20 --out ab-report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webscout_mcp.ab_eval import (  # noqa: E402
    USABLE_CONTENT_CHARS,
    ArmObservation,
    corpus_fingerprint,
    evaluate,
    observations_from_jsonl,
    observations_to_jsonl,
    render_markdown,
)

FETCH_CORPUS = REPO / "scripts" / "eval_corpus" / "fetch_urls.json"


def _load_urls(limit: int) -> list[dict[str, Any]]:
    data = json.loads(FETCH_CORPUS.read_text(encoding="utf-8"))
    entries = list(data.get("urls", []))
    if limit and limit > 0:
        entries = entries[:limit]
    return entries


async def _guarded(coro: Any, timeout: float) -> tuple[Any | None, str | None]:
    """Await with a timeout, returning (result, error_type).

    Returns the exception TYPE only - messages can embed URLs, and this data is
    written to disk and committed.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout), None
    except asyncio.TimeoutError:
        return None, "TimeoutError"
    except BaseException as exc:  # noqa: BLE001 - the type is the datum
        return None, type(exc).__name__


async def _run_live(limit: int, per_request_timeout: float, run_id: str) -> list[ArmObservation]:
    """Record both arms against the corpus.

    The two arms are driven from the same service graph so that provider
    selection, DNS handling and client pooling are identical. The only
    difference is whether the pipeline's extraction/recovery runs.
    """
    from webscout_mcp.eval_services import aclose_services, configure_eval_run
    from webscout_mcp.fetch_provider import FetchRequest
    from webscout_mcp.observability import reset_for_tests

    services = configure_eval_run(run_id)
    fetch_service = services["fetch_service"]
    registry = services.get("registry")
    http_provider = registry.get("http") if registry is not None else None

    observations: list[ArmObservation] = []
    try:
        reset_for_tests()
        for idx, entry in enumerate(_load_urls(limit)):
            url = entry["url"]
            case_id = f"{idx:03d}:{entry.get('stratum', 'unknown')}"

            # --- Arm 1: the production pipeline -------------------------------
            req = FetchRequest(
                url=url,
                extract=True,
                output_format="markdown",
                max_chars=8000,
                bypass_cache=True,
            )
            t0 = time.perf_counter()
            route, err = await _guarded(fetch_service.fetch(req), per_request_timeout)
            pipeline_ms = (time.perf_counter() - t0) * 1000.0

            if route is None:
                observations.append(
                    ArmObservation(
                        case_id=case_id,
                        arm="pipeline",
                        ok=False,
                        returned_chars=0,
                        latency_ms=pipeline_ms,
                        escaped_error=err or "unknown",
                    )
                )
            else:
                served = route.final_response.content or route.primary_response.content or ""
                meta = route.final_response.metadata or {}
                observations.append(
                    ArmObservation(
                        case_id=case_id,
                        arm="pipeline",
                        ok=True,
                        returned_chars=len(served),
                        latency_ms=pipeline_ms,
                        pre_limit_chars=meta.get("pre_limit_content_chars"),
                    )
                )

            # --- Arm 2: bare baseline ----------------------------------------
            # One GET, no extraction, no recovery, no escalation. This is what
            # an agent gets without WebScout doing anything smart.
            if http_provider is None:
                observations.append(
                    ArmObservation(
                        case_id=case_id,
                        arm="baseline",
                        ok=False,
                        returned_chars=0,
                        latency_ms=0.0,
                        escaped_error="NoHttpProvider",
                    )
                )
                continue

            t0 = time.perf_counter()
            raw, err = await _guarded(http_provider.fetch(req), per_request_timeout)
            baseline_ms = (time.perf_counter() - t0) * 1000.0

            if raw is None:
                observations.append(
                    ArmObservation(
                        case_id=case_id,
                        arm="baseline",
                        ok=False,
                        returned_chars=0,
                        latency_ms=baseline_ms,
                        escaped_error=err or "unknown",
                    )
                )
            else:
                body = raw.content or ""
                observations.append(
                    ArmObservation(
                        case_id=case_id,
                        arm="baseline",
                        ok=True,
                        returned_chars=len(body),
                        latency_ms=baseline_ms,
                    )
                )
    finally:
        await aclose_services(services)

    return observations


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B evaluation: pipeline vs bare baseline")
    ap.add_argument("--replay", type=Path, default=None, help="Re-score a recorded observations.jsonl")
    ap.add_argument("--limit", type=int, default=0, help="Cap number of URLs (0 = whole corpus)")
    ap.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    ap.add_argument("--run-id", default="ab-eval", help="Run identifier for the eval directory")
    ap.add_argument("--out", type=Path, default=None, help="Output directory for report + observations")
    ap.add_argument(
        "--threshold-chars",
        type=int,
        default=USABLE_CONTENT_CHARS,
        help="Minimum returned characters to count as usable",
    )
    ap.add_argument("--max-p95-ratio", type=float, default=1.30, help="Gate G3: pipeline/baseline P95 ratio")
    ap.add_argument(
        "--case-tolerance",
        type=int,
        default=1,
        help=(
            "Cases the pipeline may trail the baseline by before G1/G2 fail. "
            "Default 1: a single transient network failure moves a 40-case run by "
            "2.5pp and would otherwise flip the verdict on its own (observed on a "
            "real CI run). Use 0 for a strict comparison."
        ),
    )
    ap.add_argument(
        "--record",
        action="store_true",
        help="With --replay: also write the (re-scored) observations alongside the report",
    )
    args = ap.parse_args()

    if args.replay is not None:
        if not args.replay.exists():
            print(f"replay file not found: {args.replay}", file=sys.stderr)
            return 2
        observations = observations_from_jsonl(args.replay.read_text(encoding="utf-8"))
        corpus_sha = "replay:" + args.replay.stem
    else:
        observations = asyncio.run(_run_live(args.limit, args.timeout, args.run_id))
        corpus_sha = corpus_fingerprint([FETCH_CORPUS])

    result = evaluate(
        observations,
        corpus_sha=corpus_sha,
        threshold_chars=args.threshold_chars,
        max_p95_ratio=args.max_p95_ratio,
        case_tolerance=args.case_tolerance,
    )

    out_dir = args.out
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / "report.md").write_text(render_markdown(result), encoding="utf-8")
        if args.replay is None or args.record:
            (out_dir / "observations.jsonl").write_text(observations_to_jsonl(observations), encoding="utf-8")
        print(f"report written to {out_dir}")

    print(render_markdown(result))

    # Exit code carries the verdict so CI can gate on it without parsing text.
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
