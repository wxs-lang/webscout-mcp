#!/usr/bin/env python3
"""Drive the production FetchService against the curated fetch corpus.

Evaluation-only (v1.5.0 Phase 2.1). Builds the production service graph via
``configure_eval_run`` and feeds it ``FetchRequest`` objects. The driver never
constructs decisions: the DecisionEvent is created by FetchService itself.

Natural failures are recorded by the service as objective facts; we do NOT
attack sites, manufacture errors, or bypass login/captcha.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webscout_mcp.eval_runners import run_fetch_corpus  # noqa: E402
from webscout_mcp.eval_services import aclose_services, configure_eval_run  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Run production fetch corpus (evaluation)")
    ap.add_argument("--run-id", default=os.environ.get("WEBSCOUT_RUN_ID", "eval-fetch-v150"))
    ap.add_argument("--limit", type=int, default=0, help="Cap number of URLs (0 = whole corpus)")
    ap.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    args = ap.parse_args()

    services = configure_eval_run(args.run_id)
    try:
        summary = await run_fetch_corpus(
            services["fetch_service"],
            args.run_id,
            limit=args.limit,
            per_request_timeout=args.timeout,
        )
    finally:
        await aclose_services(services)

    print(
        f"fetch corpus run_id={args.run_id}: "
        f"total={summary['total']} succeeded={summary['succeeded']} failed={summary['failed']}"
    )
    print(f"decision_db={services['decision_db']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
