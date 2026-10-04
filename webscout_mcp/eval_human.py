"""Human review-pack builder + human-label import (v1.5.0 Phase 2.1).

Two evaluation-only entry points:

``build_human_review_pack(run_id, eval_dir, fetch_results, search_results)``
    Writes ``<eval_dir>/human-review.jsonl`` — one unlabeled question row per
    line a human reviewer can label. The data comes ONLY from the curated-corpus
    driver results passed in (``run_fetch_corpus`` / ``run_search_corpus``). It
    NEVER reads a production/user DB.

``import_human_labels(run_id, path)``
    Reads the labeled JSONL back. For every row whose ``expected_label`` is
    non-empty it builds a ``ReplayCase`` with ``label_source="human_verified"``
    and records it through ``decision_store.record_replay_case``. The
    ``run_id`` / ``trace_id`` / ``question`` are preserved so that the later
    offline join (``build_labeled_rows``) can correlate the human label with the
    Jev shadow prediction on ``(run_id, trace_id[, question])`` — never on
    ``case_id``.

Privacy: only the curated public corpus is touched. No credentials, tokens or
secrets are ever written into the pack.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .logging_config import get_logger

log = get_logger(__name__)

PACK_FILENAME = "human-review.jsonl"


def build_human_review_pack(
    run_id: str,
    eval_dir: str | Path,
    fetch_results: list[dict[str, Any]],
    search_results: list[dict[str, Any]],
) -> Path:
    """Build ``<eval_dir>/human-review.jsonl`` from curated-corpus driver results.

    Fetch rows (``result_usable``): one per fetch result that carries a
    non-empty production ``trace_id`` and usable content (non-error status,
    >0 chars). Context exposes only sanitized scalars + a short excerpt.

    Search rows (``result_relevant``): every individual row of every query
    result is flattened into its own relevance item, keyed by
    ``(trace_id, position)``.
    """
    eval_path = Path(eval_dir)
    eval_path.mkdir(parents=True, exist_ok=True)
    out_path = eval_path / PACK_FILENAME

    rows: list[dict[str, Any]] = []

    for fr in fetch_results or []:
        trace = str(fr.get("trace_id") or "").strip()
        if not trace:
            continue
        status = str(fr.get("status") or "")
        try:
            chars = int(fr.get("chars") or 0)
        except (TypeError, ValueError):
            chars = 0
        # "Usable context": not a transport/production error and has content.
        if status == "error" or chars <= 0:
            continue
        rows.append(
            {
                "case_id": f"human:{trace}:result_usable",
                "run_id": run_id,
                "trace_id": trace,
                "domain": "fetch",
                "question": "result_usable",
                "context": {
                    "url": fr.get("url", ""),
                    "title": fr.get("title", ""),
                    "chars": chars,
                    "status": status,
                    "excerpt": fr.get("excerpt", ""),
                },
                "expected_label": "",
            }
        )

    for sr in search_results or []:
        trace = str(sr.get("trace_id") or "").strip()
        query = str(sr.get("query") or "")
        for row in sr.get("rows") or []:
            try:
                position = int(row.get("position") or 0)
            except (TypeError, ValueError):
                position = 0
            key_trace = trace or "no-trace"
            rows.append(
                {
                    "case_id": f"human:{key_trace}:result_relevant:p{position}",
                    "run_id": run_id,
                    "trace_id": trace,
                    "domain": "search",
                    "question": "result_relevant",
                    "context": {
                        "query": query,
                        "position": position,
                        "title": row.get("title", ""),
                        "snippet": row.get("snippet", ""),
                        "url": row.get("url", ""),
                    },
                    "expected_label": "",
                }
            )

    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    log.info("eval: human review pack written to %s (%d rows)", out_path, len(rows))
    return out_path


def import_human_labels(run_id: str, path: str | Path) -> int:
    """Import labeled human-review rows as ``human_verified`` ReplayCases.

    Reads the JSONL produced (and then labeled) by a human reviewer. Rows with
    an empty ``expected_label`` are skipped. Every imported case preserves the
    original ``run_id`` / ``trace_id`` / ``question`` so the offline join on
    ``(run_id, trace_id[, question])`` can correlate it with the Jev shadow
    record. Returns the number of imported cases.
    """
    from . import decision_store
    from .decision_event import LabelSource
    from .replay_case import ReplayCase

    src = Path(path)
    imported = 0
    with src.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                log.warning("eval: skipping malformed human-label line in %s", src)
                continue
            expected = str(row.get("expected_label") or "").strip()
            if not expected:
                continue
            question = str(row.get("question") or "")
            trace_id = str(row.get("trace_id") or "")
            case = ReplayCase(
                case_id=str(row.get("case_id") or ""),
                run_id=str(row.get("run_id") or run_id),
                trace_id=trace_id,
                domain=str(row.get("domain") or "fetch"),
                input_features={"question": question, "context": row.get("context") or {}},
                observed_outcome={},
                production_decision={},
                expected_label=expected,
                label_source=LabelSource.HUMAN_VERIFIED,
                label_confidence=float(row.get("label_confidence", 1.0) or 1.0),
                label_time=time.time(),
                notes=str(row.get("notes") or ""),
            )
            if decision_store.record_replay_case(case):
                imported += 1
    log.info("eval: imported %d human labels from %s", imported, src)
    return imported
