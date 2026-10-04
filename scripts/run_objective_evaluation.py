#!/usr/bin/env python3
"""Phase 2 objective evaluation harness (offline / controlled only).

This is NOT an MCP tool. MCP tools remain 11. It is a CLI used to:

  * (optional, --live) drive Fetch/Search against the curated public corpus
    under an explicit WEBSCOUT_RUN_ID, recording DecisionEvents + Jev shadow.
  * read DecisionEvents + Jev shadow + ReplayCases for a run_id,
  * apply the objective labeler (never Jev as label source),
  * compute per-question advisor metrics + head-to-head + join gate,
  * write objective-eval-report.json / .md.

Privacy: only the curated public corpus is touched. Raw user URLs/queries are
never reconstructed from the Decision DB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webscout_mcp import decision_store, jev_store  # noqa: E402
from webscout_mcp.advisor_evaluator import (  # noqa: E402
    LabeledPrediction,
    check_join_gate,
    evaluate_question,
    semantic_label_to_ground_truth,
)
from webscout_mcp.labels import LabelTaxonomy  # noqa: E402
from webscout_mcp.objective_labeler import label_outcomes  # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parent / "eval_corpus"
OUT_DIR = REPO / ".webscout-eval"


def _corpus_hash() -> str:
    h = hashlib.sha256()
    for name in ("fetch_urls.json", "search_queries.json"):
        p = CORPUS_DIR / name
        h.update(name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def _read_events(run_id: str) -> list[dict[str, Any]]:
    db = decision_store.db_path()
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM decision_events WHERE run_id = ? ORDER BY created_at ASC", (run_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("request_features", "outcome_features", "metadata"):
            try:
                d[k] = json.loads(d[k]) if d[k] else {}
            except Exception:
                d[k] = {}
        out.append(d)
    return out


def _read_jev(run_id: str) -> list[dict[str, Any]]:
    db = jev_store.db_path()
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM jev_records WHERE run_id = ? ORDER BY timestamp ASC", (run_id,)).fetchall()
    return [dict(r) for r in rows]


def _read_replay_cases(run_id: str) -> list[dict[str, Any]]:
    db = decision_store.db_path()
    if not db.exists():
        return []
    with sqlite3.connect(str(db)) as c:
        c.row_factory = sqlite3.Row
        rows = (
            c.execute("SELECT * FROM replay_cases WHERE run_id = ? ORDER BY created_at ASC", (run_id,)).fetchall()
            if "run_id" in {r[1] for r in c.execute("PRAGMA table_info(replay_cases)")}
            else []
        )
    out = []
    for r in rows:
        d = dict(r)
        for k in ("input_features", "observed_outcome", "production_decision"):
            try:
                d[k] = json.loads(d[k]) if d[k] else {}
            except Exception:
                d[k] = {}
        out.append(d)
    return out


def build_labeled_rows(run_id: str) -> dict[str, list[LabeledPrediction]]:
    """Join Jev predictions with trusted labels per question.

    Ground truth comes ONLY from ReplayCases with label_source in
    {human_verified, objective_outcome}. Jev prediction never becomes a label.
    """
    events = _read_events(run_id)
    jev_rows = _read_jev(run_id)
    replay = _read_replay_cases(run_id)

    # Map (run_id, trace_id) -> replay label.
    label_by_trace: dict[tuple[str, str], dict[str, Any]] = {}
    for rc in replay:
        key = (rc.get("run_id", run_id), rc.get("case_id", ""))
        label_by_trace[key] = rc

    # Index Jev by (trace_id, question).
    jev_by_trace_q: dict[tuple[str, str], dict[str, Any]] = {}
    for j in jev_rows:
        jev_by_trace_q[(j.get("trace_id", ""), j.get("jev_question", ""))] = j

    questions = ["needs_escalation", "result_usable", "result_relevant"]
    rows: dict[str, list[LabeledPrediction]] = {q: [] for q in questions}

    # 1) From replay cases that carry a semantic/* expected_label.
    for rc in replay:
        src = rc.get("label_source", "")
        if src not in ("human_verified", "objective_outcome"):
            continue
        expected = rc.get("expected_label", "")
        for q in questions:
            gt = semantic_label_to_ground_truth(q, expected)
            if gt is None:
                continue
            trace = rc.get("case_id", "")
            j = jev_by_trace_q.get((trace, q))
            prob = j.get("jev_probability") if j else None
            jdec = bool(j.get("jev_decision")) if j and j.get("jev_decision") is not None else None
            rule = rc.get("production_decision", {}).get("rule_decision")
            rows[q].append(
                LabeledPrediction(
                    question=q,
                    ground_truth=gt,
                    label_source=src,
                    jev_decision=jdec,
                    jev_probability=prob,
                    rule_decision=bool(rule) if rule is not None else None,
                    trace_id=trace,
                    run_id=run_id,
                )
            )

    # 2) Ambiguous/unlabeled Jev predictions (no ground truth) -> excluded.
    for j in jev_rows:
        q = j.get("jev_question", "")
        if q not in questions:
            continue
        trace = j.get("trace_id", "")
        if any(r.trace_id == trace for r in rows[q]):
            continue
        rows[q].append(
            LabeledPrediction(
                question=q,
                ground_truth=None,
                label_source="none",
                jev_decision=bool(j.get("jev_decision")) if j.get("jev_decision") is not None else None,
                jev_probability=j.get("jev_probability"),
                rule_decision=bool(j.get("rule_decision")) if j.get("rule_decision") is not None else None,
                trace_id=trace,
                run_id=run_id,
            )
        )
    return rows


def objective_outcome_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    fetch = [e for e in events if e.get("domain") == "fetch"]
    search = [e for e in events if e.get("domain") == "search"]

    def tally(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        labeled = 0
        ambiguous = 0
        for e in rows:
            facts = e.get("outcome_features", {}) or {}
            labels = label_outcomes(e.get("domain", "fetch"), facts)
            any_obj = False
            for lr in labels:
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


def run_report(run_id: str) -> dict[str, Any]:
    events = _read_events(run_id)
    jev_rows = _read_jev(run_id)
    join = decision_store.join_report()
    gate = check_join_gate(join)
    rows = build_labeled_rows(run_id)
    qmetrics = {q: evaluate_question(q, rows[q]) for q in rows}

    obj = objective_outcome_report(events)

    # Reproducibility metadata.
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    except Exception:
        git_sha = "unknown"
    model_pairs = sorted(
        {(j.get("model_requested"), j.get("model_resolved")) for j in jev_rows if j.get("model_requested")}
    )
    sdk = ""
    try:
        import typesafe  # type: ignore

        sdk = getattr(typesafe, "__version__", "")
    except Exception:
        sdk = "typesafe-ai-not-installed"

    report = {
        "run_id": run_id,
        "git_sha": git_sha,
        "corpus_hash": _corpus_hash(),
        "taxonomy": LabelTaxonomy().to_dict(),
        "join_gate": gate.to_dict(),
        "join_report": {
            "advisor_enabled_decisions": join.get("advisor_enabled_decisions", 0),
            "joined_enabled_eligible": join.get("joined_enabled_eligible", 0),
            "unexpected_unjoined": join.get("unexpected_unjoined", 0),
            "join_coverage": join.get("join_coverage", 0.0),
        },
        "objective_outcomes": obj,
        "jev_question_metrics": {q: m.to_dict() for q, m in qmetrics.items()},
        "jev_records": len(jev_rows),
    }
    return report


def write_report(report: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp = out_dir / "objective-eval-report.json"
    mp = out_dir / "objective-eval-report.md"
    jp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    mp.write_text(_to_markdown(report), encoding="utf-8")
    return jp, mp


def _to_markdown(r: dict[str, Any]) -> str:
    lines = [
        "# Objective Decision Evaluation Report",
        "",
        f"- run_id: `{r['run_id']}`",
        f"- git_sha: `{r['git_sha']}`",
        f"- corpus_hash: `{r['corpus_hash']}`",
        f"- jev_records: {r['jev_records']}",
        "",
        "## Join gate",
        "",
        f"- passed: {r['join_gate']['passed']}",
        f"- advisor_enabled: {r['join_gate']['advisor_enabled_decisions']}",
        f"- joined: {r['join_gate']['joined_enabled_eligible']}",
        f"- unexpected_unjoined: {r['join_gate']['unexpected_unjoined']}",
        f"- coverage: {r['join_gate']['join_coverage']}",
        f"- explanation: {r['join_gate']['explanation']}",
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
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 2 objective decision evaluation harness")
    ap.add_argument("--run-id", default=os.environ.get("WEBSCOUT_RUN_ID", f"objective-v150-p2-{int(time.time())}"))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--report-only", action="store_true", default=True)
    args = ap.parse_args()

    os.environ["WEBSCOUT_RUN_ID"] = args.run_id
    report = run_report(args.run_id)
    jp, mp = write_report(report, Path(args.out_dir))
    print(f"run_id: {args.run_id}")
    print(f"wrote: {jp}")
    print(f"wrote: {mp}")
    print(json.dumps(report["join_gate"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
