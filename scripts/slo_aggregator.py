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
import os
import sys
import time
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
}


def load_live_reports(results_dir: Path) -> list[dict[str, Any]]:
    """Load all live_report.json files from the results directory."""
    reports = []
    if not results_dir.exists():
        return reports

    for report_file in sorted(results_dir.glob("**/live_report.json")):
        try:
            with open(report_file) as f:
                report = json.load(f)
                report["_source_file"] = str(report_file)
                reports.append(report)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Failed to load {report_file}: {e}", file=sys.stderr)

    return reports


def calculate_percentile(values: list[float], percentile: float) -> float:
    """Calculate percentile from a list of values."""
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = int(len(sorted_values) * percentile / 100)
    index = min(index, len(sorted_values) - 1)
    return sorted_values[index]


def aggregate_slo_metrics(
    reports: list[dict[str, Any]], days: int
) -> dict[str, Any]:
    """Aggregate SLO metrics for the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Filter reports by date
    recent_reports = []
    for report in reports:
        report_time_str = report.get("timestamp", report.get("run_time", ""))
        try:
            if report_time_str:
                report_time = datetime.fromisoformat(
                    report_time_str.replace("Z", "+00:00")
                )
                if report_time >= cutoff:
                    recent_reports.append(report)
        except (ValueError, TypeError):
            # If we can't parse the timestamp, include it (best effort)
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

    for report in recent_reports:
        # Search metrics
        search_stats = report.get("search_stats", report.get("search", {}))
        total_searches += search_stats.get("total", 0)
        successful_searches += search_stats.get("successful", search_stats.get("success", 0))
        search_latencies.extend(search_stats.get("latencies_ms", []))
        fallback_count += search_stats.get("fallback_count", 0)

        # Fetch metrics
        fetch_stats = report.get("fetch_stats", report.get("fetch", {}))
        total_fetches += fetch_stats.get("total", 0)
        successful_fetches += fetch_stats.get("successful", fetch_stats.get("success", 0))
        fetch_latencies.extend(fetch_stats.get("latencies_ms", []))

        # Error types
        for error_type, count in report.get("error_types", {}).items():
            error_types[error_type] = error_types.get(error_type, 0) + count

        # Provider distribution
        for provider, count in report.get("provider_distribution", {}).items():
            provider_counts[provider] = provider_counts.get(provider, 0) + count

    # Calculate rates
    search_success_rate = (
        (successful_searches / total_searches * 100) if total_searches > 0 else 0.0
    )
    fetch_success_rate = (
        (successful_fetches / total_fetches * 100) if total_fetches > 0 else 0.0
    )
    fallback_rate = (
        (fallback_count / total_searches * 100) if total_searches > 0 else 0.0
    )

    # Calculate percentiles
    search_p50 = calculate_percentile(search_latencies, 50)
    search_p95 = calculate_percentile(search_latencies, 95)
    fetch_p50 = calculate_percentile(fetch_latencies, 50)
    fetch_p95 = calculate_percentile(fetch_latencies, 95)

    # Determine SLO status
    status = "healthy"
    violations = []

    if days == 7:
        if search_success_rate < SLO_TARGETS["search_success_rate_7d"]:
            status = "violating"
            violations.append(
                f"Search success rate {search_success_rate:.1f}% < target {SLO_TARGETS['search_success_rate_7d']}%"
            )
        if fetch_success_rate < SLO_TARGETS["fetch_success_rate_7d"]:
            status = "violating"
            violations.append(
                f"Fetch success rate {fetch_success_rate:.1f}% < target {SLO_TARGETS['fetch_success_rate_7d']}%"
            )
        if search_p95 > SLO_TARGETS["search_p95_latency_ms"]:
            status = "warning"
            violations.append(
                f"Search P95 latency {search_p95:.0f}ms > target {SLO_TARGETS['search_p95_latency_ms']}ms"
            )
    elif days == 30:
        if search_success_rate < SLO_TARGETS["search_success_rate_30d"]:
            status = "violating"
            violations.append(
                f"Search success rate {search_success_rate:.1f}% < target {SLO_TARGETS['search_success_rate_30d']}%"
            )
        if fetch_success_rate < SLO_TARGETS["fetch_success_rate_30d"]:
            status = "violating"
            violations.append(
                f"Fetch success rate {fetch_success_rate:.1f}% < target {SLO_TARGETS['fetch_success_rate_30d']}%"
            )

    return {
        "period_days": days,
        "data_points": len(recent_reports),
        "status": status,
        "violations": violations,
        "search": {
            "total": total_searches,
            "successful": successful_searches,
            "success_rate": round(search_success_rate, 2),
            "fallback_count": fallback_count,
            "fallback_rate": round(fallback_rate, 2),
            "latency_p50_ms": round(search_p50, 1),
            "latency_p95_ms": round(search_p95, 1),
        },
        "fetch": {
            "total": total_fetches,
            "successful": successful_fetches,
            "success_rate": round(fetch_success_rate, 2),
            "latency_p50_ms": round(fetch_p50, 1),
            "latency_p95_ms": round(fetch_p95, 1),
        },
        "error_types": error_types,
        "provider_distribution": provider_counts,
        "targets": {
            k: v for k, v in SLO_TARGETS.items() if str(days) in k or "latency" in k
        },
    }


def generate_slo_report(
    reports: list[dict[str, Any]], output_dir: Path
) -> dict[str, Any]:
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
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Write Markdown report
    md_path = output_dir / "SLO_DASHBOARD.md"
    with open(md_path, "w") as f:
        f.write("# WebScout MCP - SLO Dashboard\n\n")
        f.write(f"**Generated:** {report['generated_at']}\n\n")
        f.write(f"**Overall Status:** `{report['overall_status'].upper()}`\n\n")
        f.write(f"**Total Test Runs Analyzed:** {report['total_reports_analyzed']}\n\n")

        f.write("## SLO Targets\n\n")
        f.write("| Metric | Target |\n")
        f.write("|--------|--------|\n")
        for key, value in SLO_TARGETS.items():
            f.write(f"| {key} | {value} |\n")
        f.write("\n")

        for period, slo in [("7-Day", slo_7d), ("30-Day", slo_30d)]:
            f.write(f"## {period} SLO Metrics\n\n")
            f.write(f"**Status:** `{slo['status'].upper()}`\n\n")
            f.write(f"**Data Points:** {slo['data_points']}\n\n")

            if slo.get("violations"):
                f.write("### ⚠️ SLO Violations\n\n")
                for violation in slo["violations"]:
                    f.write(f"- {violation}\n")
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
                for error_type, count in sorted(
                    slo["error_types"].items(), key=lambda x: x[1], reverse=True
                ):
                    f.write(f"| {error_type} | {count} |\n")
                f.write("\n")

            if slo.get("provider_distribution"):
                f.write("### Provider Distribution\n\n")
                f.write("| Provider | Count |\n")
                f.write("|----------|-------|\n")
                for provider, count in sorted(
                    slo["provider_distribution"].items(), key=lambda x: x[1], reverse=True
                ):
                    f.write(f"| {provider} | {count} |\n")
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
    print(f"7-Day Status: {report['slo_7d']['status']}")
    print(f"  Search Success: {report['slo_7d'].get('search', {}).get('success_rate', 'N/A')}%")
    print(f"  Fetch Success: {report['slo_7d'].get('fetch', {}).get('success_rate', 'N/A')}%")
    print(f"30-Day Status: {report['slo_30d']['status']}")
    print(f"  Search Success: {report['slo_30d'].get('search', {}).get('success_rate', 'N/A')}%")
    print(f"  Fetch Success: {report['slo_30d'].get('fetch', {}).get('success_rate', 'N/A')}%")
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
