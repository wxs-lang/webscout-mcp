#!/usr/bin/env python3
"""Drive the production SearchService against the curated search corpus.

Evaluation-only (v1.5.0 Phase 2.1). Builds the production service graph via
``configure_eval_run`` and feeds it ``SearchRequest`` objects. The driver never
builds a SearchResponse: the DecisionEvent + response come from SearchService.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webscout_mcp.eval_runners import run_search_corpus  # noqa: E402
from webscout_mcp.eval_services import aclose_services, configure_eval_run  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Run production search corpus (evaluation)")
    ap.add_argument("--run-id", default=os.environ.get("WEBSCOUT_RUN_ID", "eval-search-v150"))
    ap.add_argument("--limit", type=int, default=0, help="Cap number of queries (0 = whole corpus)")
    ap.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    args = ap.parse_args()

    services = configure_eval_run(args.run_id)
    search_service = services["search_service"]
    if search_service is None:
        print("search_live: BLOCKED — no SearchService available")
        await aclose_services(services)
        return 1
    try:
        summary = await run_search_corpus(
            search_service,
            args.run_id,
            limit=args.limit,
            per_request_timeout=args.timeout,
        )
    finally:
        await aclose_services(services)

    print(
        f"search corpus run_id={args.run_id}: "
        f"queries={summary['total']} succeeded={summary['succeeded']} "
        f"failed={summary['failed']} result_rows={summary['result_rows']}"
    )
    print(f"decision_db={services['decision_db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
