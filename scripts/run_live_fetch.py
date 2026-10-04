#!/usr/bin/env python3
"""Drive real Fetch against the curated public corpus and record DecisionEvents.

Offline/evaluation only. Uses the production Fetcher (real network, real
extraction) under an explicit WEBSCOUT_RUN_ID. Natural failures are recorded
as objective outcome facts — we do NOT attack sites, manufacture 429, or
bypass captchas/login.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webscout_mcp import decision_store, runtime_context  # noqa: E402
from webscout_mcp.config import Config  # noqa: E402
from webscout_mcp.cache import Cache  # noqa: E402
from webscout_mcp.fetcher import Fetcher  # noqa: E402

CORPUS = REPO / "scripts" / "eval_corpus" / "fetch_urls.json"


def _fake_reason_action(reason: str, action: str):
    rv = types.SimpleNamespace(value=reason)
    av = types.SimpleNamespace(value=action)
    return types.SimpleNamespace(reason=rv, action=av)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=os.environ.get("WEBSCOUT_RUN_ID", "objective-v150-p2-001"))
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    os.environ["WEBSCOUT_RUN_ID"] = args.run_id
    runtime_context.PROCESS_RUN_ID = args.run_id

    decision_store.configure(str(os.environ.get("WEBSCOUT_DECISION_DB", "")) or None)

    cfg = Config.from_env()
    cfg.ensure_dirs()
    cache = Cache(db_path=cfg.cache_dir / "webscout.db", ttl=cfg.cache_ttl, max_size_mb=cfg.cache_max_size_mb)
    fetcher = Fetcher(cfg, cache)

    data = json.loads(CORPUS.read_text())
    urls = data["urls"]
    if args.limit:
        urls = urls[: args.limit]

    from webscout_mcp.decision_adapter import record_fetch_decision

    recorded = 0
    try:
        for entry in urls:
            url = entry["url"]
            trace = runtime_context.new_trace_id()
            started = __import__("time").time()
            try:
                res = await asyncio.wait_for(
                    fetcher.fetch(url=url, extract=True, output_format="markdown", max_chars=8000, bypass_cache=True),
                    timeout=25,
                )
                status_code = int(getattr(res, "status_code", 0) or 0)
                content = getattr(res, "content", "") or ""
                chars = len(content) if isinstance(content, str) else 0
                ok = 200 <= status_code < 300 and chars > 200
                reason = "COMPLETE_CONTENT" if ok else ("PRIMARY_EMPTY" if chars <= 200 else "HTTP_ERROR")
                action = "ACCEPT" if ok else "BROWSER"
                primary = types.SimpleNamespace(
                    status="success" if ok else "error",
                    status_code=status_code,
                    web_result=None,
                    content=content,
                )
                final = types.SimpleNamespace(
                    status="success" if ok else "error",
                    web_result=None,
                    content=content,
                )
                primary_hard = "" if ok else ("SOFT_BLOCK" if status_code in (401, 403) else "TRANSPORT_FAILURE")
                record_fetch_decision(
                    request=types.SimpleNamespace(
                        url=url, max_chars=8000, start_char=0, output_format="markdown",
                        extract=True, bypass_cache=True,
                    ),
                    primary=primary,
                    final=final,
                    recovery=_fake_reason_action(reason, action),
                    recovery_outcome="accepted" if ok else "attempted",
                    primary_provider="http",
                    browser_attempted=False,
                    browser_success=False,
                    fallback_used=False,
                    fallback_success=False,
                    primary_hard_signal=primary_hard,
                    trace_id=trace,
                    run_id=args.run_id,
                    started_at=started,
                )
                recorded += 1
                print(f"  [{recorded:03d}] {status_code} {chars:6d}ch  {url}")
            except Exception as exc:
                # Natural failure -> record as objective failure event.
                primary = types.SimpleNamespace(status="error", status_code=0, web_result=None, content="")
                record_fetch_decision(
                    request=types.SimpleNamespace(
                        url=url, max_chars=8000, start_char=0, output_format="markdown",
                        extract=True, bypass_cache=True,
                    ),
                    primary=primary,
                    final=primary,
                    recovery=_fake_reason_action("TRANSPORT_FAILURE", "BROWSER"),
                    recovery_outcome="failed",
                    primary_provider="http",
                    browser_attempted=False,
                    browser_success=False,
                    fallback_used=False,
                    primary_hard_signal="TRANSPORT_FAILURE",
                    trace_id=trace,
                    run_id=args.run_id,
                    started_at=started,
                )
                recorded += 1
                print(f"  [{recorded:03d}] ERR {type(exc).__name__}: {url}")
    finally:
        await fetcher.close()

    print(f"\nrecorded {recorded} fetch DecisionEvents under run_id={args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
