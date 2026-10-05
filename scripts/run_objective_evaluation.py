#!/usr/bin/env python3
"""WebScout v1.5.0 Phase 2.1 UNIFIED objective evaluation CLI.

Evaluation-only. It changes NO production routing, recovery decision, Jev
semantics (Jev stays a pure shadow) and NO MCP tool surface (still 11 tools).

Three mutually exclusive modes (default = report-only):

  * ``--live``              async pipeline: bootstrap the production service
                           graph scoped to ``--run-id`` via ``configure_eval_run``,
                           drive the curated Fetch/Search corpus runners,
                           optionally run the browser counterfactual sweep,
                           drain Jev, materialize objective replay cases, build
                           the human review pack and write the run report.
  * ``--report-only``       sync, ZERO network and ZERO service construction.
                           Reads an existing run's per-run SQLite DBs (if they
                           already exist) and writes ``objective-eval-report``.
  * ``--preflight``         capability probe; prints text, returns 0 only when
                           all four capabilities are READY (else 2).

Reports + run artifacts live under ``<out-dir>/<run_id>/``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webscout_mcp import decision_store, eval_human, jev_store  # noqa: E402
from webscout_mcp.advisor_evaluator import (  # noqa: E402
    build_jev_prediction_index,
    build_labeled_rows,
    check_join_gate,
    evaluate_question,
)
from webscout_mcp.jev_store import is_valid_jev_prediction  # noqa: E402
from webscout_mcp.eval_preflight import run_preflight, to_text  # noqa: E402
from webscout_mcp.eval_runners import (  # noqa: E402
    run_browser_counterfactual,
    run_fetch_corpus,
    run_search_corpus,
)
from webscout_mcp.eval_services import aclose_services, configure_eval_run  # noqa: E402
from webscout_mcp.labels import LabelTaxonomy  # noqa: E402
from webscout_mcp.objective_labeler import label_outcomes, materialize_objective_replay_cases  # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parent / "eval_corpus"
DEFAULT_OUT_DIR = REPO / ".webscout-eval"

REPORT_JSON = "objective-eval-report.json"
REPORT_MD = "objective-eval-report.md"

# Real-run gate thresholds (Phase 2.1 acceptance bar).
# The Search real-run gate counts Jev result_relevant PREDICTIONS (distinct
# resolved trace+position keys), NOT raw result rows. result rows are observability.
REAL_RUN_THRESHOLDS = {
    "fetch_total": 60,
    "search_total": 40,
    "search_relevance_predictions": 100,
    "browser_counterfactual": 20,
}
# Human-label gate thresholds.
HUMAN_LABEL_THRESHOLDS = {
    "fetch_usable": 20,
    "search_relevant": 30,
}


# ---------------------------------------------------------------------------
# Reproducibility helpers.
# ---------------------------------------------------------------------------


def _corpus_hash() -> str:
    h = hashlib.sha256()
    for name in ("fetch_urls.json", "search_queries.json"):
        p = CORPUS_DIR / name
        h.update(name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:  # noqa: BLE001 - best effort
        return "unknown"


def _sdk_version() -> str:
    """TypeSafe SDK version. The module is ``typesafe_sdk``; ``typesafe`` is a
    legacy fallback; otherwise a not-installed marker."""
    for mod_name in ("typesafe_sdk", "typesafe"):
        try:
            mod = __import__(mod_name)
            version = getattr(mod, "__version__", None)
        except Exception:  # noqa: BLE001 - noqa: F401, defensive
            version = None
        if version:
            return str(version)
    return "not-installed"


def _default_run_id() -> str:
    return os.environ.get("WEBSCOUT_RUN_ID") or f"objective-v150-p21-{int(time.time())}"


def _read_jev_rows(run_id: str) -> list[dict[str, Any]]:
    """Read the run's Jev shadow rows straight from the configured jev DB."""
    db = jev_store.db_path()
    if not db.exists():
        return []
    try:
        with sqlite3.connect(str(db), timeout=5.0) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("SELECT * FROM jev_records WHERE run_id = ?", (run_id,)).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def _objective_outcome_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    fetch = [e for e in events if e.get("domain") == "fetch"]
    search = [e for e in events if e.get("domain") == "search"]

    def tally(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        labeled = 0
        ambiguous = 0
        for e in rows:
            facts = e.get("outcome_features", {}) or {}
            any_obj = False
            for lr in label_outcomes(e.get("domain", "fetch"), facts):
                if lr.is_objective and lr.label:
                    counts[lr.label] = counts.get(lr.label, 0) + 1
                    any_obj = True
            if any_obj:
                labeled += 1
            else:
                ambiguous += 1
        counts["_objective_labeled_events"] = labeled
        counts["_ambiguous_events"] = ambiguous
        counts["_total_events"] = len(rows)
        return counts

    return {
        "fetch": tally(fetch),
        "search": tally(search),
        "fetch_total": len(fetch),
        "search_total": len(search),
    }


def _replay_question(rc: dict[str, Any]) -> str:
    q = (rc.get("input_features") or {}).get("question")
    if not q:
        q = (rc.get("production_decision") or {}).get("question")
    return str(q or "")


def _browser_counterfactual_count(run_dir: Path) -> int:
    p = run_dir / "browser-counterfactual.jsonl"
    if not p.exists():
        return 0
    try:
        with p.open("r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def _valid_prediction_stats(jev_rows: list[dict[str, Any]], question: str) -> tuple[int, int, set[tuple[Any, ...]]]:
    """Count distinct resolved-key VALID predictions for one Jev question.

    Only rows where ``jev_question == question`` AND
    :func:`is_valid_jev_prediction` holds are eligible (timeout /
    missing_answer / malformed_response / API / SDK error rows are NOT
    predictions). Duplicate keys are resolved with the valid-beats-error
    priority so a newer error row cannot un-seat an older valid one.

    Returns ``(valid_prediction_count, duplicate_prediction_keys, keys)``.
    """
    rel_rows = [j for j in jev_rows if j.get("jev_question") == question and is_valid_jev_prediction(j)]
    index, dupes = build_jev_prediction_index(rel_rows)
    return len(index), dupes, set(index.keys())


def _search_relevance_prediction_stats(
    jev_rows: list[dict[str, Any]],
) -> tuple[int, int, set[tuple[Any, ...]]]:
    """Count distinct valid Jev ``result_relevant`` predictions.

    A prediction requires jev_question=result_relevant AND a valid prediction
    (empty error, float probability in [0,1], decision present), counted per
    resolved distinct (trace, position) key with duplicate resolution. Returns
    ``(prediction_count, duplicate_prediction_keys, prediction_keys)``.

    100 malformed rows (prob 0.0 / decision False / error malformed_response)
    yield count 0.
    """
    return _valid_prediction_stats(jev_rows, "result_relevant")


def _expected_shadow_rows(search_events: list[dict[str, Any]]) -> tuple[int, int, str]:
    """Expected per-result shadow denominator.

    ``sum over search events of min(result_count, jev_search_shadow_max_results)``.
    The cap is read from Config (default 10). Returns ``(expected, cap, source)``
    where source is ``config`` or ``default``.
    """
    cap = 10
    source = "default"
    try:
        from webscout_mcp.config import Config

        cap = int(Config.from_env().jev_search_shadow_max_results)
        source = "config"
    except Exception:  # noqa: BLE001 - never fabricate a precise denominator
        cap = 10
    expected = 0
    for e in search_events:
        try:
            rc = int((e.get("outcome_features") or {}).get("result_count") or 0)
        except (TypeError, ValueError):
            rc = 0
        expected += min(max(rc, 0), cap)
    return expected, cap, source


# ---------------------------------------------------------------------------
# Report assembly.
# ---------------------------------------------------------------------------


def build_run_report(run_id: str) -> dict[str, Any]:
    """Assemble ONE run-scoped evaluation report dict. Read-only."""
    events = decision_store.load_events_for_run(run_id)
    jev_rows = _read_jev_rows(run_id)
    replay_cases = decision_store.load_replay_cases(run_id=run_id)
    run_dir = decision_store.db_path().parent

    # --- Reproducibility / model metadata (never credentials) ----------------
    model_pairs = sorted(
        {
            (str(j.get("model_requested") or ""), str(j.get("model_resolved") or ""))
            for j in jev_rows
            if j.get("model_requested")
        }
    )
    pair_counts = Counter(
        (str(j.get("model_requested") or ""), str(j.get("model_resolved") or ""))
        for j in jev_rows
        if j.get("model_requested")
    )
    if pair_counts:
        model_requested, model_resolved = pair_counts.most_common(1)[0][0]
    else:
        model_requested, model_resolved = "", ""

    # --- Run-scoped join gate -----------------------------------------------
    join_report = decision_store.join_report(run_id=run_id)
    join_gate = check_join_gate(join_report).to_dict()

    # --- Labeled rows / per-question metrics --------------------------------
    join_result = build_labeled_rows(run_id)
    rows = join_result.rows
    jev_question_metrics = {q: evaluate_question(q, rows[q]).to_dict() for q in rows}

    # --- Objective outcome summary (from production facts, never Jev) --------
    objective_outcomes = _objective_outcome_report(events)

    # --- Counts --------------------------------------------------------------
    fetch_events = [e for e in events if e.get("domain") == "fetch"]
    search_events = [e for e in events if e.get("domain") == "search"]
    search_result_rows = 0
    for e in search_events:
        try:
            search_result_rows += int((e.get("outcome_features") or {}).get("result_count") or 0)
        except (TypeError, ValueError):
            pass
    objective_materialized = sum(1 for rc in replay_cases if rc.get("label_source") == "objective_outcome")
    browser_cf_count = _browser_counterfactual_count(run_dir)

    # Search relevance: Jev PREDICTIONS (distinct trace+position), not result rows.
    (
        search_relevance_predictions,
        duplicate_prediction_keys,
        relevance_prediction_keys,
    ) = _search_relevance_prediction_stats(jev_rows)
    # Fetch questions: distinct valid predictions per resolved (run,trace,question).
    (
        needs_escalation_predictions,
        _ne_dupes,
        _ne_keys,
    ) = _valid_prediction_stats(jev_rows, "needs_escalation")
    (
        result_usable_predictions,
        _ru_dupes,
        _ru_keys,
    ) = _valid_prediction_stats(jev_rows, "result_usable")
    expected_shadow_rows, shadow_cap, shadow_cap_source = _expected_shadow_rows(search_events)
    if expected_shadow_rows > 0:
        prediction_coverage: float | None = round(search_relevance_predictions / expected_shadow_rows, 4)
        coverage_denominator_upper_bound = False
    else:
        # No reliable per-result denominator: report predictions over raw result
        # rows and explicitly flag it as an UPPER-BOUND denominator — never a
        # fabricated precise coverage.
        prediction_coverage = (
            round(search_relevance_predictions / search_result_rows, 4) if search_result_rows > 0 else None
        )
        coverage_denominator_upper_bound = True

    counts = {
        "events_total": len(events),
        "fetch_events": len(fetch_events),
        "search_events": len(search_events),
        "jev_records": len(jev_rows),
        "replay_cases": len(replay_cases),
        "objective_materialized": objective_materialized,
        "search_result_rows": search_result_rows,
        "search_relevance_predictions": search_relevance_predictions,
        "needs_escalation_predictions": needs_escalation_predictions,
        "result_usable_predictions": result_usable_predictions,
        "expected_shadow_rows": expected_shadow_rows,
        "jev_search_shadow_max_results": shadow_cap,
        "prediction_coverage": prediction_coverage,
        "prediction_coverage_denominator_is_upper_bound": coverage_denominator_upper_bound,
        "duplicate_prediction_keys": duplicate_prediction_keys,
        "browser_counterfactual_cases": browser_cf_count,
    }

    # --- Advisor availability: valid predictions vs error records -----------
    # Over the run's RAW jev_rows (observability), NOT the labeled subset.
    advisor_valid = sum(1 for j in jev_rows if is_valid_jev_prediction(j))
    advisor_stats = {
        "jev_records_total": len(jev_rows),
        "jev_valid_predictions": advisor_valid,
        "jev_error_records": len(jev_rows) - advisor_valid,
        "jev_valid_rate": round(advisor_valid / len(jev_rows), 4) if jev_rows else None,
    }

    # Per-question join stats + the evaluation advisor_prediction_coverage.
    advisor_by_question: dict[str, dict[str, Any]] = {}
    for q, s in join_result.stats.items():
        advisor_by_question[q] = {
            "rows": s["rows"],
            "valid_predictions": s["valid_predictions"],
            "errors": s["errors"],
            "labeled_with_valid_prediction": s["labeled_with_valid_prediction"],
            "labeled_missing_valid_prediction": s["labeled_missing_valid_prediction"],
            "advisor_prediction_coverage": jev_question_metrics[q]["advisor_prediction_coverage"],
        }

    # --- Real-run gate -------------------------------------------------------
    advisor_enabled = int(join_report.get("advisor_enabled_decisions", 0) or 0)
    unexpected_unjoined = int(join_report.get("unexpected_unjoined", 0) or 0)
    join_coverage = float(join_report.get("join_coverage", 0.0) or 0.0)
    real_run_gate = {
        "fetch_total": counts["fetch_events"],
        "search_total": counts["search_events"],
        "search_result_rows": search_result_rows,
        "search_relevance_predictions": search_relevance_predictions,
        "needs_escalation_predictions": needs_escalation_predictions,
        "result_usable_predictions": result_usable_predictions,
        "prediction_coverage": prediction_coverage,
        "prediction_coverage_denominator_is_upper_bound": coverage_denominator_upper_bound,
        "browser_counterfactual_cases": browser_cf_count,
        "advisor_enabled_decisions": advisor_enabled,
        "unexpected_unjoined": unexpected_unjoined,
        "join_coverage": join_coverage,
        "thresholds": dict(REAL_RUN_THRESHOLDS),
        "passed_fetch_total": counts["fetch_events"] >= REAL_RUN_THRESHOLDS["fetch_total"],
        "passed_search_total": counts["search_events"] >= REAL_RUN_THRESHOLDS["search_total"],
        "passed_search_relevance_predictions": search_relevance_predictions
        >= REAL_RUN_THRESHOLDS["search_relevance_predictions"],
        "passed_needs_escalation_predictions": needs_escalation_predictions > 0,
        "passed_result_usable_predictions": result_usable_predictions > 0,
        "passed_browser_counterfactual": browser_cf_count >= REAL_RUN_THRESHOLDS["browser_counterfactual"],
        "passed_advisor_enabled": advisor_enabled > 0,
        "passed_no_unexpected_unjoined": unexpected_unjoined == 0,
        "passed_join_coverage": join_coverage == 1.0,
    }
    real_run_pass = all(v for k, v in real_run_gate.items() if k.startswith("passed_"))

    # --- Human-label gate (STRICTLY human_verified) --------------------------
    # A label counts toward the human gate ONLY when label_source == human_verified.
    # Objective/materialized result_usable labels must NOT inflate the Fetch human
    # count, and objective result_relevant must always be 0 (relevance is human-only).
    def _is_human(rc: dict[str, Any]) -> bool:
        return rc.get("label_source") == "human_verified"

    def _is_objective(rc: dict[str, Any]) -> bool:
        return rc.get("label_source") == "objective_outcome"

    human_fetch_usable = sum(
        1
        for rc in replay_cases
        if _replay_question(rc) == "result_usable" and rc.get("expected_label") and _is_human(rc)
    )
    objective_fetch_usable = sum(
        1
        for rc in replay_cases
        if _replay_question(rc) == "result_usable" and rc.get("expected_label") and _is_objective(rc)
    )
    human_search_relevant = sum(
        1
        for rc in replay_cases
        if _replay_question(rc) == "result_relevant" and rc.get("expected_label") and _is_human(rc)
    )
    objective_search_relevant = sum(
        1
        for rc in replay_cases
        if _replay_question(rc) == "result_relevant" and rc.get("expected_label") and _is_objective(rc)
    )

    # Operation-level vs per-result coverage: the (run,trace) join_report proves
    # >=1 Jev row per Search operation; here we separately count how many human
    # relevance labels actually joined a per-result prediction (by position).
    human_relevance_joined = 0
    human_relevance_missing_prediction = 0
    for rc in replay_cases:
        if _replay_question(rc) != "result_relevant" or not rc.get("expected_label") or not _is_human(rc):
            continue
        ctx = (rc.get("input_features") or {}).get("context") or {}
        position = ctx.get("position")
        if isinstance(position, bool) or not isinstance(position, int):
            position = None
        key = (rc.get("run_id") or run_id, rc.get("trace_id") or "", "result_relevant", position)
        if key in relevance_prediction_keys:
            human_relevance_joined += 1
        else:
            human_relevance_missing_prediction += 1

    human_gate = {
        "human_fetch_usable": human_fetch_usable,
        "objective_fetch_usable": objective_fetch_usable,
        "human_search_relevant": human_search_relevant,
        "objective_search_relevant": objective_search_relevant,
        "search_relevance_prediction_count": search_relevance_predictions,
        "human_relevance_joined_count": human_relevance_joined,
        "human_relevance_missing_prediction": human_relevance_missing_prediction,
        "operation_join_coverage": join_coverage,
        "thresholds": dict(HUMAN_LABEL_THRESHOLDS),
        "passed_fetch_usable": human_fetch_usable >= HUMAN_LABEL_THRESHOLDS["fetch_usable"],
        "passed_search_relevance": human_search_relevant >= HUMAN_LABEL_THRESHOLDS["search_relevant"],
    }
    human_pass = human_gate["passed_fetch_usable"] and human_gate["passed_search_relevance"]

    # --- Overall status (never "Phase 2 complete") ---------------------------
    status_parts: list[str] = []
    if not real_run_pass:
        status_parts.append("PHASE2_REAL_EVAL_INCOMPLETE")
    if not human_pass:
        status_parts.append("HUMAN_EVAL_INCOMPLETE")
    status = "READY" if not status_parts else "+".join(status_parts)

    return {
        "run_id": run_id,
        "git_sha": _git_sha(),
        "corpus_hash": _corpus_hash(),
        "sdk_version": _sdk_version(),
        "model_pairs": model_pairs,
        "model_requested": model_requested,
        "model_resolved": model_resolved,
        "decision_db": str(decision_store.db_path().resolve()),
        "jev_db": str(jev_store.db_path().resolve()),
        "taxonomy": LabelTaxonomy().to_dict(),
        "join_report": join_report,
        "join_gate": join_gate,
        "jev_question_metrics": jev_question_metrics,
        "advisor_stats": advisor_stats,
        "advisor_by_question": advisor_by_question,
        "objective_outcomes": objective_outcomes,
        "counts": counts,
        "real_run_gate": real_run_gate,
        "human_gate": human_gate,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Report writing.
# ---------------------------------------------------------------------------


def write_report(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / REPORT_JSON
    mp = out_dir / REPORT_MD
    jp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    mp.write_text(_to_markdown(report), encoding="utf-8")
    return jp, mp


def _to_markdown(r: dict[str, Any]) -> str:
    jg = r["join_gate"]
    rr = r["real_run_gate"]
    hg = r["human_gate"]
    lines = [
        "# Objective Decision Evaluation Report",
        "",
        "## Reproducibility",
        "",
        f"- run_id: `{r['run_id']}`",
        f"- git_sha: `{r['git_sha']}`",
        f"- corpus_hash: `{r['corpus_hash']}`",
        f"- sdk_version: `{r['sdk_version']}`",
        f"- model_requested: `{r.get('model_requested', '')}`",
        f"- model_resolved: `{r.get('model_resolved', '')}`",
        f"- model_pairs: `{r.get('model_pairs', [])}`",
        f"- decision_db: `{r['decision_db']}`",
        f"- jev_db: `{r['jev_db']}`",
        f"- status: **{r['status']}**",
        "",
        "## Counts",
        "",
        "```json",
        json.dumps(r["counts"], indent=2),
        "```",
        "",
        "## Join gate",
        "",
        f"- passed: {jg['passed']}",
        f"- advisor_enabled: {jg['advisor_enabled_decisions']}",
        f"- joined: {jg['joined_enabled_eligible']}",
        f"- unexpected_unjoined: {jg['unexpected_unjoined']}",
        f"- coverage: {jg['join_coverage']}",
        f"- explanation: {jg['explanation']}",
        "",
        "## Real-run gate",
        "",
        "```json",
        json.dumps(rr, indent=2),
        "```",
        "",
        "## Human-label gate",
        "",
        "```json",
        json.dumps(hg, indent=2),
        "```",
        "",
        "## Objective outcomes",
        "",
        "```json",
        json.dumps(r["objective_outcomes"], indent=2),
        "```",
        "",
        "## Jev question metrics",
        "",
        "```json",
        json.dumps(r["jev_question_metrics"], indent=2),
        "```",
        "",
        "## Advisor availability",
        "",
        "```json",
        json.dumps(r.get("advisor_stats", {}), indent=2),
        "```",
        "",
        "```json",
        json.dumps(r.get("advisor_by_question", {}), indent=2),
        "```",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode handlers.
# ---------------------------------------------------------------------------


def _resolve_run_dir(out_dir: Path, run_id: str) -> Path:
    """Locate an existing per-run directory.

    Prefers ``<out-dir>/<run_id>`` (the documented layout). Falls back to
    ``<out-dir>/.webscout-eval/<run_id>`` for runs bootstrapped directly by
    ``configure_eval_run(base_dir=out_dir)``. If neither exists, the documented
    path is returned so report-only writes a canonical artifact location.
    """
    primary = out_dir / run_id
    if (primary / "decision.db").exists():
        return primary
    nested = out_dir / ".webscout-eval" / run_id
    if (nested / "decision.db").exists():
        return nested
    return primary


def _handle_preflight() -> int:
    report = run_preflight()
    print(to_text(report))
    capabilities = report.get("capabilities", {})
    ready = all(v.get("status") == "READY" for v in capabilities.values())
    return 0 if ready else 2


def _handle_report_only(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    run_dir = _resolve_run_dir(out_dir, args.run_id)
    decision_db = run_dir / "decision.db"
    jev_db = run_dir / "jev.db"
    if not (decision_db.exists() and jev_db.exists()):
        # FAIL CLOSED: never fall back to the global/default decision DB or any
        # other run's DB. The run DBs are configured only when BOTH exist for
        # the requested run; otherwise refuse (and never let --import-human-labels
        # write elsewhere).
        missing = [p.name for p in (decision_db, jev_db) if not p.exists()]
        print(
            f"error: report-only requires per-run DBs in {run_dir}; missing: {', '.join(missing)}. "
            "Refusing to fall back to the global/default DB or another run's DB.",
            file=sys.stderr,
        )
        return 2
    # Both run DBs exist: configure them (CREATE IF NOT EXISTS); no network,
    # no service construction.
    decision_store.configure(decision_db)
    jev_store.configure(jev_db)

    if args.import_human_labels:
        n = eval_human.import_human_labels(args.run_id, args.import_human_labels)
        print(f"imported human labels: {n}")

    report = build_run_report(args.run_id)
    jp, mp = write_report(report, run_dir)
    print(f"run_id: {args.run_id}")
    print(f"wrote: {jp}")
    print(f"wrote: {mp}")
    print(f"status: {report['status']}")
    print("join gate:")
    print(json.dumps(report["join_gate"], indent=2))
    return 0


async def _handle_live(args: argparse.Namespace) -> int:
    services = configure_eval_run(args.run_id, base_dir=Path(args.out_dir))

    fetch_out = await run_fetch_corpus(services["fetch_service"], args.run_id, limit=args.fetch_limit)
    search_out: dict[str, Any] = {"results": []}
    if services.get("search_service") is not None:
        search_out = await run_search_corpus(services["search_service"], args.run_id, limit=args.search_limit)

    if args.with_browser_counterfactual:
        await run_browser_counterfactual(services, args.run_id)

    # Drain all Jev shadow tasks BEFORE reading any store.
    await aclose_services(services)

    n_objective = materialize_objective_replay_cases(args.run_id)

    eval_dir = Path(services["eval_dir"])
    pack_path = eval_human.build_human_review_pack(
        args.run_id,
        eval_dir,
        fetch_out.get("results", []),
        search_out.get("results", []),
    )

    report = build_run_report(args.run_id)
    jp, mp = write_report(report, eval_dir)

    print(f"run_id: {args.run_id}")
    print(
        f"fetch: total={fetch_out.get('total')} succeeded={fetch_out.get('succeeded')} failed={fetch_out.get('failed')}"
    )
    print(
        f"search: total={search_out.get('total')} succeeded={search_out.get('succeeded')} "
        f"failed={search_out.get('failed')} result_rows={search_out.get('result_rows')}"
    )
    print(f"objective replay cases materialized: {n_objective}")
    print(f"human review pack: {pack_path}")
    print(f"wrote: {jp}")
    print(f"wrote: {mp}")
    print(f"status: {report['status']}")
    print("join gate:")
    print(json.dumps(report["join_gate"], indent=2))
    return 0


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="WebScout v1.5.0 Phase 2.1 unified objective evaluation CLI (evaluation-only)."
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Run the live corpus pipeline (network).")
    mode.add_argument(
        "--report-only",
        action="store_true",
        help="Report from an existing run's per-run DBs (default; zero network).",
    )
    mode.add_argument("--preflight", action="store_true", help="Capability probe only.")
    ap.add_argument("--run-id", default=_default_run_id())
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument(
        "--with-browser-counterfactual",
        action="store_true",
        help="Also run the browser counterfactual sweep (only valid with --live).",
    )
    ap.add_argument(
        "--import-human-labels",
        dest="import_human_labels",
        default=None,
        metavar="FILE",
        help="Import labeled human-review JSONL (report-only mode), then build the report.",
    )
    ap.add_argument("--fetch-limit", type=int, default=0, help="Limit fetch corpus entries (0 = all).")
    ap.add_argument("--search-limit", type=int, default=0, help="Limit search corpus entries (0 = all).")
    args = ap.parse_args(argv)

    if args.with_browser_counterfactual and not args.live:
        ap.error("--with-browser-counterfactual is only valid with --live")
    if args.import_human_labels and (args.live or args.preflight):
        ap.error("--import-human-labels combines with report-only mode (the default or --report-only)")

    os.environ["WEBSCOUT_RUN_ID"] = args.run_id

    if args.preflight:
        return _handle_preflight()
    if args.live:
        return asyncio.run(_handle_live(args))
    return _handle_report_only(args)


if __name__ == "__main__":
    raise SystemExit(main())
