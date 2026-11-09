#!/usr/bin/env python3
"""Generate 100 Fetch + 100 Search ReplayCases from deterministic fixtures.

These cases are used to seed the offline evaluation dataset. They cover all
major recovery actions and outcomes. 429/timeout/403/parser-drift/network
errors are simulated via fixtures (no real site attacks).

Usage:
    python scripts/generate_replay_cases.py [--db PATH]
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

# Ensure repo root is on path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from webscout_mcp.decision_event import LabelSource, sanitized_url_features, query_hash
from webscout_mcp.decision_store import configure, record_replay_case
from webscout_mcp.replay_case import ReplayCase


def _uid(prefix: str, i: int) -> str:
    return f"{prefix}-{i:04d}-{uuid.uuid4().hex[:8]}"


def _fetch_cases() -> list[ReplayCase]:
    """Generate 100 Fetch replay cases."""
    cases: list[ReplayCase] = []

    # Distribution:
    #   ACCEPT / COMPLETE_CONTENT:       25
    #   ACCEPT / COMPLETE_SHORT_PAGE:    10
    #   CONTINUE_CONTENT / OUTPUT_TRUNCATED: 20
    #   BROWSER / JS_REQUIRED:           10
    #   BROWSER / SOFT_BLOCK:             5
    #   BROWSER / LOW_CONTENT_DENSITY:    5
    #   PROVIDER_FALLBACK / TLS_FAILURE:  5
    #   RETRY / NETWORK_FAILURE:          5
    #   RETRY_LATER / RATE_LIMITED:       5
    #   STOP / ACCESS_DENIED:             3
    #   STOP / LEGAL_BLOCKED:             2
    #   NONE / AMBIGUOUS:                 5
    distributions = [
        (
            "ACCEPT",
            "COMPLETE_CONTENT",
            "accepted",
            25,
            {"status": "success", "http_status_group": "2xx", "content_chars": 15000, "extraction_success": True},
        ),
        (
            "ACCEPT",
            "COMPLETE_SHORT_PAGE",
            "accepted",
            10,
            {"status": "success", "http_status_group": "2xx", "content_chars": 1200, "extraction_success": True},
        ),
        (
            "CONTINUE_CONTENT",
            "OUTPUT_TRUNCATED",
            "continuation_ready",
            20,
            {
                "status": "partial",
                "http_status_group": "2xx",
                "content_chars": 8000,
                "pre_limit_chars": 90000,
                "truncated": True,
                "continuation_available": True,
            },
        ),
        (
            "BROWSER",
            "JS_REQUIRED",
            "browser_success",
            10,
            {
                "status": "success",
                "http_status_group": "2xx",
                "browser_used": True,
                "browser_success": True,
                "content_chars": 12000,
            },
        ),
        (
            "BROWSER",
            "SOFT_BLOCK",
            "browser_success",
            5,
            {"status": "success", "http_status_group": "4xx", "browser_used": True, "browser_success": True},
        ),
        (
            "BROWSER",
            "LOW_CONTENT_DENSITY",
            "browser_success",
            5,
            {"status": "success", "browser_used": True, "browser_success": True},
        ),
        (
            "PROVIDER_FALLBACK",
            "TLS_FAILURE",
            "fallback_success",
            5,
            {"status": "success", "fallback_used": True, "http_status_group": "0xx"},
        ),
        ("RETRY", "NETWORK_FAILURE", "retry_delegated_to_fetcher", 5, {"status": "error", "http_status_group": "0xx"}),
        (
            "RETRY_LATER",
            "RATE_LIMITED",
            "deferred",
            5,
            {"status": "error", "http_status_group": "4xx", "http_status_code": 429},
        ),
        (
            "STOP",
            "ACCESS_DENIED",
            "terminal",
            3,
            {"status": "error", "http_status_group": "4xx", "http_status_code": 403},
        ),
        (
            "STOP",
            "LEGAL_BLOCKED",
            "terminal",
            2,
            {"status": "error", "http_status_group": "4xx", "http_status_code": 451},
        ),
        ("NONE", "AMBIGUOUS", "no_action", 5, {"status": "success", "http_status_group": "2xx"}),
    ]

    idx = 0
    for action, reason, outcome, count, outcome_base in distributions:
        for i in range(count):
            idx += 1
            url = f"https://example-{reason.lower()}-{i}.com/page"
            url_feat = sanitized_url_features(url)
            input_features = {
                "url": url_feat,
                "extract": True,
                "output_format": "markdown",
                "max_chars": 8000,
                "start_char": 0,
                "bypass_cache": False,
            }
            observed = dict(outcome_base)
            observed["primary_provider"] = "http"
            production_decision = {
                "reason": reason,
                "action": action,
                "outcome": outcome,
                "confidence": 0.9 if action != "NONE" else 0.4,
            }
            # Expected label: for browser/fallback, check if it actually rescued.
            if action == "BROWSER" and outcome == "browser_success":
                expected = "BROWSER"
            elif action == "PROVIDER_FALLBACK" and outcome == "fallback_success":
                expected = "PROVIDER_FALLBACK"
            elif action == "CONTINUE_CONTENT":
                expected = "CONTINUE_CONTENT"
            elif action == "STOP":
                expected = "STOP"
            elif action == "RETRY_LATER":
                expected = "RETRY_LATER"
            elif action == "RETRY":
                expected = "RETRY"
            elif action == "NONE":
                expected = "NONE"
            else:
                expected = "ACCEPT"

            cases.append(
                ReplayCase(
                    case_id=_uid("fetch", idx),
                    domain="fetch",
                    input_features=input_features,
                    observed_outcome=observed,
                    production_decision=production_decision,
                    expected_label=expected,
                    label_source=LabelSource.DETERMINISTIC_FIXTURE,
                    label_confidence=1.0,
                    label_time=time.time(),
                    notes=f"Fixture: {reason} -> {action} -> {outcome}",
                )
            )
    return cases


def _search_cases() -> list[ReplayCase]:
    """Generate 100 Search replay cases."""
    cases: list[ReplayCase] = []

    distributions = [
        # (action, reason, outcome, count, outcome_base)
        (
            "ACCEPT",
            "RESULT_AVAILABLE",
            "accepted",
            30,
            {"status": "success", "result_count": 8, "provider_attempt_count": 1},
        ),
        (
            "ACCEPT",
            "RESULT_AVAILABLE",
            "accepted",
            10,
            {"status": "success", "result_count": 5, "provider_attempt_count": 2, "fallback_count": 1},
        ),
        (
            "TRY_NEXT_PROVIDER",
            "EMPTY_RESULT",
            "next_provider",
            10,
            {"status": "empty", "result_count": 0, "provider_attempt_count": 2},
        ),
        (
            "TRY_NEXT_PROVIDER",
            "TIMEOUT",
            "next_provider",
            8,
            {"status": "error", "result_count": 0, "provider_attempt_count": 2},
        ),
        (
            "TRY_NEXT_PROVIDER",
            "RATE_LIMITED",
            "next_provider",
            5,
            {"status": "error", "result_count": 0, "provider_attempt_count": 2},
        ),
        (
            "TRY_NEXT_PROVIDER",
            "AUTH_ERROR",
            "next_provider",
            5,
            {"status": "error", "result_count": 0, "provider_attempt_count": 2},
        ),
        (
            "TRY_NEXT_PROVIDER",
            "PARSER_FAILURE",
            "next_provider",
            5,
            {"status": "error", "result_count": 0, "provider_attempt_count": 2},
        ),
        (
            "TRY_NEXT_PROVIDER",
            "NETWORK_FAILURE",
            "next_provider",
            5,
            {"status": "error", "result_count": 0, "provider_attempt_count": 2},
        ),
        (
            "RETURN_EMPTY",
            "ALL_EMPTY",
            "returned_empty",
            8,
            {"status": "empty", "result_count": 0, "provider_attempt_count": 3},
        ),
        (
            "RETURN_ERROR",
            "ALL_FAILED",
            "returned_error",
            5,
            {"status": "error", "result_count": 0, "provider_attempt_count": 3},
        ),
        ("STOP", "INVALID_QUERY", "stopped", 4, {"status": "error", "result_count": 0, "provider_attempt_count": 0}),
        (
            "TRY_NEXT_PROVIDER",
            "CIRCUIT_OPEN",
            "circuit_skipped",
            3,
            {"status": "success", "result_count": 5, "provider_attempt_count": 2, "circuit_skips": 1},
        ),
        (
            "TRY_NEXT_PROVIDER",
            "UNAVAILABLE",
            "unavailable_skipped",
            2,
            {"status": "success", "result_count": 5, "provider_attempt_count": 2, "unavailable_skips": 1},
        ),
    ]

    idx = 0
    providers = ["bing", "duckduckgo", "searxng", "tavily"]
    for action, reason, outcome, count, outcome_base in distributions:
        for i in range(count):
            idx += 1
            q = f"test query {reason} {i}"
            input_features = {
                "query_hash": query_hash(q),
                "query_length": len(q),
                "max_results": 10,
                "safe_search": True,
                "region": "wt-wt",
                "language": "en",
                "country": "",
            }
            observed = dict(outcome_base)
            observed["final_provider"] = providers[idx % len(providers)]
            production_decision = {
                "reason": reason,
                "action": action,
                "outcome": outcome,
                "confidence": 0.9 if action != "TRY_NEXT_PROVIDER" else 0.85,
            }
            if action == "ACCEPT":
                expected = "ACCEPT"
            elif action == "RETURN_EMPTY":
                expected = "RETURN_EMPTY"
            elif action == "RETURN_ERROR":
                expected = "RETURN_ERROR"
            elif action == "STOP":
                expected = "STOP"
            else:
                expected = "TRY_NEXT_PROVIDER"

            cases.append(
                ReplayCase(
                    case_id=_uid("search", idx),
                    domain="search",
                    input_features=input_features,
                    observed_outcome=observed,
                    production_decision=production_decision,
                    expected_label=expected,
                    label_source=LabelSource.DETERMINISTIC_FIXTURE,
                    label_confidence=1.0,
                    label_time=time.time(),
                    notes=f"Fixture: {reason} -> {action} -> {outcome}",
                )
            )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate replay cases from fixtures")
    parser.add_argument("--db", default=None, help="Decision DB path")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    args = parser.parse_args()

    fetch_cases = _fetch_cases()
    search_cases = _search_cases()
    print(f"Generated {len(fetch_cases)} fetch cases, {len(search_cases)} search cases")

    if args.dry_run:
        for c in fetch_cases[:3] + search_cases[:3]:
            print(f"  {c.domain:6s} {c.expected_label:20s} {c.production_decision.get('reason', '?')}")
        return

    db = configure(args.db)
    print(f"Writing to {db}")
    written = 0
    for case in fetch_cases + search_cases:
        if record_replay_case(case):
            written += 1
    print(f"Written {written} replay cases")


if __name__ == "__main__":
    main()
