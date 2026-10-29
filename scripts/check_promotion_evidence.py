#!/usr/bin/env python3
"""F4: a Stable rating must be backed by the evidence the standard requires.

REFACTOR_PLAN.md states the promotion bar:

    Experimental -> Beta    unit tests, no severe static errors, real E2E,
                            at least 20 real scenarios
    Beta -> Stable          30 days of live tests, success-rate target met,
                            no P0/P1 bugs, MCP E2E green, Windows/Linux/macOS,
                            Python 3.10/3.11/3.12, at least one real MCP client

MODULE_STATUS.md declares nine tools Stable. Live-test history began 2026-10-25,
so none of them can have 30 days behind that claim yet.

That is not a reason to fail a build - the tools shipped and users depend on them.
It is a reason to stop the gap being invisible. This script measures the actual
evidence and states the shortfall, so the claim and the data are on the same page
instead of one being asserted and the other never read.

Exit codes:
    0   reported (always, unless --require is given)
    1   --require was given and the evidence is insufficient
    2   the inputs could not be read
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REQUIRED_DAYS = 30

_STAMP = re.compile(r"(\d{8})T\d{6}Z")
_TOOL_ROW = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|[^|]*\|\s*([^|]*?)\s*\|", re.MULTILINE)


def stable_tools(status_file: Path) -> list[str]:
    """Tools MODULE_STATUS.md declares Stable.

    Read from the generated doc rather than a second hardcoded list: the doc is
    what the project tells its users, so the check should measure that claim and
    not a copy of it that can drift.
    """
    if not status_file.exists():
        raise FileNotFoundError(status_file)
    text = status_file.read_text(encoding="utf-8")
    names = []
    for name, level in _TOOL_ROW.findall(text):
        if "Stable" in level:
            names.append(name)
    return sorted(set(names))


def report_days(history_root: Path) -> list[datetime]:
    """Distinct UTC dates that have at least one live report.

    The branch stores runs/<run-id>-<YYYYMMDDTHHMMSSZ>/live_report.json, so the
    directory name carries the date without parsing report payloads. Days, not
    runs: three runs in one day is still one day of evidence.
    """
    if not history_root.exists():
        return []
    days: set[str] = set()
    for path in history_root.rglob("live_report.json"):
        match = _STAMP.search(str(path.parent.name))
        if match:
            days.add(match.group(1))
            continue
        # Fall back to the report's own timestamp when the directory is unusual.
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            ts = payload.get("timestamp")
            if isinstance(ts, (int, float)) and ts > 0:
                days.add(datetime.fromtimestamp(ts, UTC).strftime("%Y%m%d"))
        except (OSError, ValueError):
            continue
    return sorted(datetime.strptime(d, "%Y%m%d").replace(tzinfo=UTC) for d in days)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check F4 promotion evidence")
    parser.add_argument(
        "--status-file",
        type=Path,
        default=REPO / "MODULE_STATUS.md",
        help="File declaring tool stability levels",
    )
    parser.add_argument(
        "--history-root",
        type=Path,
        default=REPO / "live-test-results" / "history",
        help="Directory containing restored slo-history runs",
    )
    parser.add_argument(
        "--required-days",
        type=int,
        default=REQUIRED_DAYS,
        help="Days of live testing required for Beta -> Stable",
    )
    parser.add_argument(
        "--require",
        action="store_true",
        help="Exit 1 when the evidence is insufficient (default: report only)",
    )
    args = parser.parse_args(argv)

    try:
        tools = stable_tools(args.status_file)
    except FileNotFoundError as exc:
        print(f"::error::cannot read {exc}", file=sys.stderr)
        return 2

    days = report_days(args.history_root)
    count = len(days)

    print("=== F4 promotion evidence ===")
    print(f"Required for Beta -> Stable: {args.required_days} day(s) of live tests")
    print()
    print("Live-test history:")
    if days:
        span = (days[-1] - days[0]).days + 1
        print(f"  days with data : {count}")
        print(f"  first          : {days[0].date().isoformat()}")
        print(f"  last           : {days[-1].date().isoformat()}")
        print(f"  calendar span  : {span} day(s)")
    else:
        print("  no live-test history found")
    print()

    print(f"Tools declared Stable by {args.status_file.name}: {len(tools)}")
    for name in tools:
        print(f"  {name}")
    print()

    if count >= args.required_days:
        print(f"OK: {count} day(s) of evidence meet the {args.required_days}-day bar.")
        return 0

    shortfall = args.required_days - count
    print(
        f"GAP: {count} of {args.required_days} day(s) of live-test evidence. "
        f"{len(tools)} tool(s) are declared Stable {shortfall} day(s) before the "
        f"standard's bar."
    )
    print(
        "This is a known, measured gap rather than a build failure: the tools are "
        "published and in use. Tracking it here keeps the claim and the evidence "
        "from diverging silently."
    )
    # GitHub step summary, when running in Actions. Guard on the value being
    # non-empty: Path("") is Path("."), which fails with EACCES on open("a").
    summary_env = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    summary = Path(summary_env) if summary_env else None
    if summary is not None and summary.parent.exists():
        with summary.open("a", encoding="utf-8") as fh:
            fh.write(
                f"### F4 promotion evidence\n\n"
                f"- Required: {args.required_days} days of live tests\n"
                f"- On record: {count} days\n"
                f"- Declared Stable: {len(tools)} tool(s)\n"
                f"- **Shortfall: {shortfall} day(s)**\n"
            )

    return 1 if args.require else 0


if __name__ == "__main__":
    sys.exit(main())
