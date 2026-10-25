#!/usr/bin/env python3
"""
SLO (Service Level Objective) Aggregator for WebScout MCP

Collects historical Live Test results from GitHub Actions artifacts,
aggregates them into 7-day and 30-day SLO metrics, and generates
a dashboard report.

SLO Metrics:
- Search success rate (7d/30d)
- Fetch success rate (7d/30d)
- P50/P95 search latency
- P50/P95 fetch latency
- Fallback rate (Bing -> DDG/Tavily)
- Error rate by type (403/429/timeout/DNS/SSL)
- Provider distribution
- MCP tool error rate
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# SLO Targets (can be overridden via environment variables)
SLO_TARGETS = {
    "search_success_rate_7d": float(os.getenv("SLO_SEARCH_SUCCESS_7D", "99.0")),
    "search_success_rate_30d": float(os.getenv("SLO_SEARCH_SUCCESS_30D", "98.0")),
    "fetch_success_rate_7d": float(os.getenv("SLO_FETCH_SUCCESS_7D", "98.0")),
    "fetch_success_rate_30d": float(os.getenv("SLO_FETCH_SUCCESS_30D", "97.0")),
    "mcp_e2e_success_rate_7d": float(os.getenv("SLO_MCP_SUCCESS_7D", "99.5")),
    "search_p95_latency_ms": float(os.getenv("SLO_SEARCH_P95", "5000")),
    "fetch_p95_latency_ms": float(os.getenv("SLO_FETCH_P95", "10000")),
    # Content-quality targets (GOAL G1/G5). Percentages, higher is better for
    # usable content; lower is better for thin and truncation.
    "usable_content_rate_min": float(os.getenv("SLO_USABLE_CONTENT_RATE", "85.0")),
    "thin_content_rate_max": float(os.getenv("SLO_THIN_CONTENT_RATE", "10.0")),
    "truncation_rate_max": float(os.getenv("SLO_TRUNCATION_RATE", "25.0")),
}


def _extract_content_quality(report: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the content-quality block out of a report, if the run recorded one.

    Accepts both a snapshot written by ``observability.write_snapshot`` (nested
    under ``content_quality``) and a flat layout. Returns None when the report
    predates content-quality instrumentation, so old reports keep contributing
    their success/latency numbers without being counted as zero-quality.
    """
    block = report.get("content_quality")
    if not isinstance(block, dict) or not block:
        return None
    try:
        fetches = int(block.get("fetches", 0) or 0)
    except (TypeError, ValueError):
        return None
    if fetches <= 0:
        return None
    return {
        "fetches": fetches,
        "usable": int(block.get("usable", 0) or 0),
        "thin": int(block.get("thin", 0) or 0),
        "empty": int(block.get("empty", 0) or 0),
        "truncated": int(block.get("truncated_by_output_limit", 0) or 0),
    }


def load_live_reports(results_dir: Path) -> list[dict[str, Any]]:
    """Load all live_report.json files from the results directory."""
    reports = []
    if not results_dir.exists():
        return reports

    for report_file in sorted(results_dir.glob("**/live_report.json")):
        try:
            with open(report_file, encoding="utf-8") as f:
                report = json.load(f)
                report["_source_file"] = str(report_file)
                reports.append(report)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Failed to load {report_file}: {e}", file=sys.stderr)

    return reports


def calculate_percentile(values: list[float], percentile: float) -> float:
    """Calculate percentile from a list of values (nearest-rank method)."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = math.ceil(len(sorted_values) * percentile / 100) - 1
    index = max(0, min(index, len(sorted_values) - 1))
    return sorted_values[index]


def _parse_report_time(report: dict[str, Any]) -> datetime | None:
    """Parse the report timestamp robustly.

    Supports:
    - float/int epoch timestamps (seconds since 1970-01-01 UTC, as written
      by ``LiveTestReport.timestamp`` via ``time.time()``)
    - ISO-8601 strings, with or without a trailing ``Z``
    - ``datetime`` objects (naive timestamps are assumed to be UTC)

    Returns ``None`` when the field is missing or empty (legacy reports are
    included best-effort). Raises ``ValueError`` when the field exists but
    cannot be parsed — a data/code error that must surface instead of being
    silently swallowed (prevents "green CI, broken monitoring").
    """
    raw = report.get("timestamp", report.get("run_time", ""))
    if raw is None or raw == "":
        return None

    if isinstance(raw, (int, float)):
        # Epoch timestamp (seconds since 1970-01-01 UTC)
        return datetime.fromtimestamp(raw, tz=timezone.utc)

    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=timezone.utc)
        return raw

    if isinstance(raw, str):
        text = raw.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            # Not ISO — try numeric epoch string
            try:
                return datetime.fromtimestamp(float(text), tz=timezone.utc)
            except ValueError:
                raise ValueError(f"Cannot parse report timestamp: {raw!r}") from None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    raise ValueError(f"Unsupported report timestamp type: {type(raw).__name__} ({raw!r})")


def _extract_stats(section: dict[str, Any]) -> dict[str, Any]:
    """Normalize a report section into a common metric dict.

    Supports both the current layout written by tests/live/test_live_search.py
    (``search``/``fetch`` with ``count``/``success_count``/``success_rate``/
    ``p50_latency_ms``/``p95_latency_ms``/``error_types``/``providers``) and
    the legacy layout (``search_stats``/``fetch_stats`` with ``total``/
    ``successful``/``latencies_ms``/``fallback_count``).
    """
    return {
        "total": section.get("total", section.get("count", 0)),
        "successful": section.get(
            "successful",
            section.get("success", section.get("success_count", 0)),
        ),
        "latencies": section.get("latencies_ms", None),
        "p50": section.get("p50_latency_ms", None),
        "p95": section.get("p95_latency_ms", None),
        "fallback_count": section.get("fallback_count", 0),
        "error_types": section.get("error_types", {}),
        "providers": section.get("providers", section.get("provider_distribution", {})),
    }


def _append_latencies(target: list[float], stats: dict[str, Any]) -> None:
    """Collect latency samples, falling back to reported percentiles."""
    raw = stats["latencies"]
    if isinstance(raw, (int, float)):
        target.append(float(raw))
    elif raw:
        target.extend(float(v) for v in raw)
    else:
        # No raw latency array (current report layout): use the reported
        # P50 and P95 as representative samples so percentile metrics are
        # not empty and both percentiles are distinguishable.
        if stats["p50"] is not None:
            target.append(float(stats["p50"]))
        if stats["p95"] is not None:
            target.append(float(stats["p95"]))


def aggregate_slo_metrics(reports: list[dict[str, Any]], days: int) -> dict[str, Any]:
    """Aggregate SLO metrics for the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Filter reports by date
    recent_reports = []
    for report in reports:
        try:
            report_time = _parse_report_time(report)
        except ValueError as e:
            # Data/code error: fail loudly instead of silently including
            source = report.get("_source_file", "unknown")
            raise ValueError(f"Invalid timestamp in report {source}: {e}") from e
        if report_time is None:
            # Missing/empty timestamp: include best effort (legacy reports)
            recent_reports.append(report)
            continue
        if report_time >= cutoff:
            recent_reports.append(report)

    if not recent_reports:
        return {
            "period_days": days,
            "data_points": 0,
            "status": "no_data",
            "message": f"No live test data in the last {days} days",
        }

    # Aggregate metrics
    total_searches = 0
    successful_searches = 0
    total_fetches = 0
    successful_fetches = 0
    search_latencies = []
    fetch_latencies = []
    fallback_count = 0
    error_types: dict[str, int] = {}
    provider_counts: dict[str, int] = {}
    cq_fetches = 0
    cq_usable = 0
    cq_thin = 0
    cq_empty = 0
    cq_truncated = 0
    cq_reports = 0

    for report in recent_reports:
        # Content quality (GOAL G1/G5). Absent on reports that predate the
        # instrumentation; those are skipped rather than counted as zero.
        cq = _extract_content_quality(report)
        if cq is not None:
            cq_reports += 1
            cq_fetches += cq["fetches"]
            cq_usable += cq["usable"]
            cq_thin += cq["thin"]
            cq_empty += cq["empty"]
            cq_truncated += cq["truncated"]

        # Search metrics
        search_stats = _extract_stats(report.get("search_stats", report.get("search", {})))
        total_searches += search_stats["total"]
        successful_searches += search_stats["successful"]
        _append_latencies(search_latencies, search_stats)
        fallback_count += search_stats["fallback_count"]

        # Fetch metrics
        fetch_stats = _extract_stats(report.get("fetch_stats", report.get("fetch", {})))
        total_fetches += fetch_stats["total"]
        successful_fetches += fetch_stats["successful"]
        _append_latencies(fetch_latencies, fetch_stats)

        # Fallback section (current layout: top-level "fallback" with count)
        fallback_section = report.get("fallback", {})
        if isinstance(fallback_section, dict):
            fallback_count += fallback_section.get("count", fallback_section.get("success_count", 0))

        # Error types (per-section in current layout, top-level in legacy)
        for section in (search_stats, fetch_stats):
            for error_type, count in section["error_types"].items():
                error_types[error_type] = error_types.get(error_type, 0) + count
        for error_type, count in report.get("error_types", {}).items():
            error_types[error_type] = error_types.get(error_type, 0) + count

        # Provider distribution (per-section in current layout, top-level in legacy)
        for section in (search_stats, fetch_stats):
            for provider, count in section["providers"].items():
                provider_counts[provider] = provider_counts.get(provider, 0) + count
        for provider, count in report.get("provider_distribution", {}).items():
            provider_counts[provider] = provider_counts.get(provider, 0) + count

    # Calculate rates.
    #
    # None means "no observations", which is a different finding from 0.0%,
    # which means "every observation failed". Collapsing the two made a run
    # with no data report a violation: total=0 produced rate 0.0 and the gate
    # read it as a total outage. That inverts the meaning of the metric and
    # trains people to ignore real violations.
    search_success_rate = (successful_searches / total_searches * 100) if total_searches > 0 else None
    fetch_success_rate = (successful_fetches / total_fetches * 100) if total_fetches > 0 else None
    fallback_rate = (fallback_count / total_searches * 100) if total_searches > 0 else 0.0

    # Calculate percentiles
    search_p50 = calculate_percentile(search_latencies, 50)
    search_p95 = calculate_percentile(search_latencies, 95)
    fetch_p50 = calculate_percentile(fetch_latencies, 50)
    fetch_p95 = calculate_percentile(fetch_latencies, 95)

    # Content quality rates. None (not 0.0) when no report carried the block:
    # "no data" and "zero usable content" are very different findings.
    if cq_fetches > 0:
        usable_content_rate = cq_usable / cq_fetches * 100
        thin_content_rate = cq_thin / cq_fetches * 100
        empty_content_rate = cq_empty / cq_fetches * 100
        truncation_rate = cq_truncated / cq_fetches * 100
    else:
        usable_content_rate = thin_content_rate = empty_content_rate = truncation_rate = None

    # Determine SLO status
    status = "healthy"
    violations = []

    if days == 7:
        if search_success_rate is not None and search_success_rate < SLO_TARGETS["search_success_rate_7d"]:
            status = "violating"
            violations.append(
                f"Search success rate {search_success_rate:.1f}% < target {SLO_TARGETS['search_success_rate_7d']}%"
            )
        if fetch_success_rate is not None and fetch_success_rate < SLO_TARGETS["fetch_success_rate_7d"]:
            status = "violating"
            violations.append(
                f"Fetch success rate {fetch_success_rate:.1f}% < target {SLO_TARGETS['fetch_success_rate_7d']}%"
            )
        if total_searches > 0 and search_p95 > SLO_TARGETS["search_p95_latency_ms"]:
            status = "warning"
            violations.append(
                f"Search P95 latency {search_p95:.0f}ms > target {SLO_TARGETS['search_p95_latency_ms']}ms"
            )
    elif days == 30:
        if search_success_rate is not None and search_success_rate < SLO_TARGETS["search_success_rate_30d"]:
            status = "violating"
            violations.append(
                f"Search success rate {search_success_rate:.1f}% < target {SLO_TARGETS['search_success_rate_30d']}%"
            )
        if fetch_success_rate is not None and fetch_success_rate < SLO_TARGETS["fetch_success_rate_30d"]:
            status = "violating"
            violations.append(
                f"Fetch success rate {fetch_success_rate:.1f}% < target {SLO_TARGETS['fetch_success_rate_30d']}%"
            )

    # Content-quality gates. Usable content is a hard violation: the whole
    # point of the layer is returning content worth reading. Thin content and
    # truncation are warnings — both can spike for reasons the layer controls
    # only partially (a site adding a captcha, a legitimately huge page).
    if usable_content_rate is not None:
        if usable_content_rate < SLO_TARGETS["usable_content_rate_min"]:
            status = "violating"
            violations.append(
                f"Usable content rate {usable_content_rate:.1f}% < target {SLO_TARGETS['usable_content_rate_min']}%"
            )
        if thin_content_rate > SLO_TARGETS["thin_content_rate_max"]:
            if status == "healthy":
                status = "warning"
            violations.append(
                f"Thin content rate {thin_content_rate:.1f}% > target {SLO_TARGETS['thin_content_rate_max']}%"
            )
        if truncation_rate > SLO_TARGETS["truncation_rate_max"]:
            if status == "healthy":
                status = "warning"
            violations.append(f"Truncation rate {truncation_rate:.1f}% > target {SLO_TARGETS['truncation_rate_max']}%")

    # A window full of reports that recorded nothing is not "healthy". Treat it
    # as no_data so a pipeline that never actually ran anything cannot present a
    # green SLO. This distinguishes three states that were previously smeared
    # together: no reports, reports with no observations, and reports showing
    # failures.
    if total_searches == 0 and total_fetches == 0 and cq_fetches == 0 and status == "healthy":
        status = "no_data"
        violations.append(
            "reports were present but contained no observations "
            f"({len(recent_reports)} report(s) in the last {days} days)"
        )

    return {
        "period_days": days,
        "data_points": len(recent_reports),
        "status": status,
        "violations": violations,
        "search": {
            "total": total_searches,
            "successful": successful_searches,
            "success_rate": None if search_success_rate is None else round(search_success_rate, 2),
            "fallback_count": fallback_count,
            "fallback_rate": round(fallback_rate, 2),
            "latency_p50_ms": round(search_p50, 1),
            "latency_p95_ms": round(search_p95, 1),
        },
        "fetch": {
            "total": total_fetches,
            "successful": successful_fetches,
            "success_rate": None if fetch_success_rate is None else round(fetch_success_rate, 2),
            "latency_p50_ms": round(fetch_p50, 1),
            "latency_p95_ms": round(fetch_p95, 1),
        },
        "content_quality": {
            "reports_with_data": cq_reports,
            "fetches": cq_fetches,
            "usable": cq_usable,
            "thin": cq_thin,
            "empty": cq_empty,
            "truncated_by_output_limit": cq_truncated,
            "usable_rate": None if usable_content_rate is None else round(usable_content_rate, 2),
            "thin_rate": None if thin_content_rate is None else round(thin_content_rate, 2),
            "empty_rate": None if empty_content_rate is None else round(empty_content_rate, 2),
            "truncation_rate": None if truncation_rate is None else round(truncation_rate, 2),
            "status": "no_data" if usable_content_rate is None else "measured",
        },
        "error_types": error_types,
        "provider_distribution": provider_counts,
        "targets": {k: v for k, v in SLO_TARGETS.items() if str(days) in k or "latency" in k},
    }


def generate_slo_report(reports: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    """Generate complete SLO report with 7d and 30d metrics."""
    output_dir.mkdir(parents=True, exist_ok=True)

    slo_7d = aggregate_slo_metrics(reports, 7)
    slo_30d = aggregate_slo_metrics(reports, 30)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_reports_analyzed": len(reports),
        "slo_7d": slo_7d,
        "slo_30d": slo_30d,
        "overall_status": (
            "no_data"
            if slo_7d["status"] == "no_data" and slo_30d["status"] == "no_data"
            else "healthy"
            if slo_7d["status"] == "healthy" and slo_30d["status"] in ("healthy", "no_data")
            else "warning"
            if slo_7d["status"] == "warning" or slo_30d["status"] == "warning"
            else "violating"
        ),
    }

    # Write JSON report
    json_path = output_dir / "slo_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    # Write Markdown report
    md_path = output_dir / "SLO_DASHBOARD.md"
    # Encoding is explicit: the default is locale-dependent, and this file
    # contains status glyphs (⚠️, ❌, 📊) that cp936 cannot encode. Without this,
    # generating the dashboard crashes on Windows with UnicodeEncodeError.
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# WebScout MCP - SLO Dashboard\n\n")
        f.write(f"**Generated:** {report['generated_at']}\n\n")
        f.write(f"**Overall Status:** `{report['overall_status'].upper()}`\n\n")
        f.write(f"**Total Test Runs Analyzed:** {report['total_reports_analyzed']}\n\n")

        f.write("## SLO Targets\n\n")
        f.write("| Metric | Target |\n")
        f.write("|--------|--------|\n")
        f.writelines(f"| {key} | {value} |\n" for key, value in SLO_TARGETS.items())
        f.write("\n")

        for period, slo in [("7-Day", slo_7d), ("30-Day", slo_30d)]:
            f.write(f"## {period} SLO Metrics\n\n")
            f.write(f"**Status:** `{slo['status'].upper()}`\n\n")
            f.write(f"**Data Points:** {slo['data_points']}\n\n")

            if slo.get("violations"):
                f.write("### ⚠️ SLO Violations\n\n")
                f.writelines(f"- {violation}\n" for violation in slo["violations"])
                f.write("\n")

            f.write("### Search\n\n")
            f.write("| Metric | Value |\n")
            f.write("|--------|-------|\n")
            search = slo.get("search", {})
            f.write(f"| Total Searches | {search.get('total', 0)} |\n")
            f.write(f"| Successful | {search.get('successful', 0)} |\n")
            f.write(f"| Success Rate | **{search.get('success_rate', 0)}%** |\n")
            f.write(f"| Fallback Count | {search.get('fallback_count', 0)} |\n")
            f.write(f"| Fallback Rate | {search.get('fallback_rate', 0)}% |\n")
            f.write(f"| Latency P50 | {search.get('latency_p50_ms', 0)}ms |\n")
            f.write(f"| Latency P95 | **{search.get('latency_p95_ms', 0)}ms** |\n")
            f.write("\n")

            f.write("### Fetch\n\n")
            f.write("| Metric | Value |\n")
            f.write("|--------|-------|\n")
            fetch = slo.get("fetch", {})
            f.write(f"| Total Fetches | {fetch.get('total', 0)} |\n")
            f.write(f"| Successful | {fetch.get('successful', 0)} |\n")
            f.write(f"| Success Rate | **{fetch.get('success_rate', 0)}%** |\n")
            f.write(f"| Latency P50 | {fetch.get('latency_p50_ms', 0)}ms |\n")
            f.write(f"| Latency P95 | **{fetch.get('latency_p95_ms', 0)}ms** |\n")
            f.write("\n")

            if slo.get("error_types"):
                f.write("### Error Types\n\n")
                f.write("| Error Type | Count |\n")
                f.write("|------------|-------|\n")
                f.writelines(
                    f"| {error_type} | {count} |\n"
                    for error_type, count in sorted(slo["error_types"].items(), key=lambda x: x[1], reverse=True)
                )
                f.write("\n")

            if slo.get("provider_distribution"):
                f.write("### Provider Distribution\n\n")
                f.write("| Provider | Count |\n")
                f.write("|----------|-------|\n")
                f.writelines(
                    f"| {provider} | {count} |\n"
                    for provider, count in sorted(
                        slo["provider_distribution"].items(), key=lambda x: x[1], reverse=True
                    )
                )
                f.write("\n")

    print(f"SLO report generated: {json_path}")
    print(f"SLO dashboard: {md_path}")
    print(f"Overall status: {report['overall_status']}")

    return report


def main():
    """Main entry point for SLO aggregation."""
    results_dir = PROJECT_ROOT / "live-test-results"
    output_dir = PROJECT_ROOT / "slo-reports"

    print("=" * 60)
    print("WebScout MCP - SLO Aggregator")
    print("=" * 60)
    print(f"Results directory: {results_dir}")
    print(f"Output directory: {output_dir}")
    print()

    # Load live reports
    reports = load_live_reports(results_dir)
    print(f"Loaded {len(reports)} live test reports")

    if not reports:
        print("Warning: No live test reports found. SLO report will show 'no_data'.")
        print("Run live tests first to populate SLO metrics.")

    # Generate SLO report
    report = generate_slo_report(reports, output_dir)

    print()
    print("=" * 60)
    print("SLO Summary")
    print("=" * 60)

    def _fmt(pct: object) -> str:
        # None means "no observations in this window", which must not print as
        # "0.0%" - that reads as a total outage.
        return "N/A (no data)" if pct is None else f"{pct}%"

    print(f"7-Day Status: {report['slo_7d']['status']}")
    print(f"  Search Success: {_fmt(report['slo_7d'].get('search', {}).get('success_rate'))}")
    print(f"  Fetch Success:  {_fmt(report['slo_7d'].get('fetch', {}).get('success_rate'))}")
    print(f"30-Day Status: {report['slo_30d']['status']}")
    print(f"  Search Success: {_fmt(report['slo_30d'].get('search', {}).get('success_rate'))}")
    print(f"  Fetch Success:  {_fmt(report['slo_30d'].get('fetch', {}).get('success_rate'))}")
    print(f"Overall: {report['overall_status']}")

    # Exit with error if SLO is violating (but not if no_data)
    if report["overall_status"] == "violating":
        print()
        print("❌ SLO VIOLATION DETECTED - exiting with error")
        sys.exit(1)
    elif report["overall_status"] == "warning":
        print()
        print("⚠️  SLO WARNING - some metrics below targets")
        sys.exit(0)
    elif report["overall_status"] == "no_data":
        print()
        print("📊 No SLO data yet - run live tests to populate metrics")
        sys.exit(0)
    else:
        print()
        print("✅ All SLO targets met")
        sys.exit(0)


if __name__ == "__main__":
    main()
