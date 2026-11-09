#!/usr/bin/env python3

"""Run the browser counterfactual sweep (evaluation-only).

For a curated fetch subset this independently compares the FAST/HTTP path and the
Crawl4AI browser backend, without going through production recovery. It writes
raw facts to ``.webscout-eval/<run-id>/browser-counterfactual.jsonl`` and does
NOT infer "browser_required" from a positive char gain.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webscout_mcp.eval_runners import run_browser_counterfactual  # noqa: E402
from webscout_mcp.eval_services import aclose_services, configure_eval_run  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Run browser counterfactual sweep (evaluation)")
    ap.add_argument("--run-id", default=os.environ.get("WEBSCOUT_RUN_ID", "eval-bcf-v150"))
    ap.add_argument("--limit", type=int, default=0, help="Number of cases (0 = curated default ~24)")
    args = ap.parse_args()

    services = configure_eval_run(args.run_id)
    if services.get("browser_backend") is None:
        print("browser_counterfactual: BLOCKED — Crawl4AI sidecar not configured")
        await aclose_services(services)
        return 1
    try:
        cases = await run_browser_counterfactual(services, args.run_id, limit=args.limit)
    finally:
        await aclose_services(services)

    print(f"browser counterfactual run_id={args.run_id}: {len(cases)} cases")
    print(f"artifact={services['eval_dir'] / 'browser-counterfactual.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
