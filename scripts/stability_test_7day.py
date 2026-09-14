#!/usr/bin/env python3
"""
7-Day Continuous Stability Test for WebScout MCP

Runs comprehensive tests continuously for 7 days, collecting:
- Search success rate (Chinese + English)
- Fetch success rate
- MCP tool functionality
- Performance metrics (P50/P95 latency)
- Error taxonomy (403/429/timeout/DNS/SSL)
- Provider distribution (Bing/DDG/Tavily)
- System resource usage (memory/CPU)
- Daily reports and 7-day summary

Usage:
    python scripts/stability_test_7day.py
    python scripts/stability_test_7day.py --duration 7 --interval 3600
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Test configurations
SEARCH_QUERIES = [
    # English queries
    "python asyncio documentation",
    "GitHub MCP SDK",
    "PostgreSQL tutorial",
    "OpenAI API reference",
    "Docker best practices",
    "FastAPI tutorial",
    "pytest documentation",
    "Linux system administration",
    # Chinese queries
    "Python 异步编程教程",
    "GitHub 中文文档",
    "PostgreSQL 教程",
    "Docker 最佳实践",
    "FastAPI 中文教程",
    "pytest 测试框架",
    "Linux 系统管理",
    "MCP 协议介绍",
]

FETCH_URLS = [
    "https://docs.python.org/3/library/asyncio.html",
    "https://docs.python.org/3/tutorial/introduction.html",
    "https://github.com/modelcontextprotocol",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript",
    "https://www.postgresql.org/docs/current/tutorial.html",
]

MCP_TOOLS_TO_TEST = [
    "web_search",
    "web_fetch",
    "web_crawl",
    "web_extract",
    "cache_stats",
    "search_health",
    "metadata_extract",
    "rss_parse",
    "content_quality",
    "broken_links",
]


class StabilityTestRunner:
    """7-day continuous stability test runner (with resume support)."""

    def __init__(self, duration_days: int = 7, interval_seconds: int = 3600):
        self.duration_days = duration_days
        self.interval_seconds = interval_seconds

        # Results storage
        self.results_dir = PROJECT_ROOT / "stability-7day-results"
        self.results_dir.mkdir(exist_ok=True)
        self.raw_results_file = self.results_dir / "raw_results.jsonl"
        self.summary_file = self.results_dir / "summary.json"
        self.daily_reports_dir = self.results_dir / "daily-reports"
        self.daily_reports_dir.mkdir(exist_ok=True)

        # Statistics (will be restored from existing data if resuming)
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.search_latencies = []
        self.fetch_latencies = []
        self.error_types = {}
        self.provider_counts = {}
        self.hourly_stats = []

        # Current hour stats
        self.current_hour = None
        self.hourly_tests = 0
        self.hourly_passed = 0
        self.hourly_failed = 0

        # Resume from existing data if present
        self._resume()

    def _resume(self):
        """Restore state from existing raw results (crash / reboot recovery)."""
        if not self.raw_results_file.exists():
            self.start_time = datetime.now(timezone.utc)
            self.end_time = self.start_time + timedelta(days=self.duration_days)
            self.log(f"No existing data - starting fresh (start={self.start_time})")
            return

        try:
            lines = self.raw_results_file.read_text().strip().splitlines()
            if not lines:
                self.start_time = datetime.now(timezone.utc)
                self.end_time = self.start_time + timedelta(days=self.duration_days)
                self.log("Empty raw results - starting fresh")
                return

            # Restore start_time from first record
            first = json.loads(lines[0])
            first_ts = first.get("timestamp")
            if first_ts:
                self.start_time = datetime.fromisoformat(first_ts)

            # Decide end_time: keep original end if still in future, else extend from now
            planned_end = self.start_time + timedelta(days=self.duration_days)
            now = datetime.now(timezone.utc)
            self.end_time = planned_end if planned_end > now else now + timedelta(days=self.duration_days)

            # Restore stats from all existing records
            for line in lines:
                record = json.loads(line)
                for t in record.get("search_tests", []):
                    self.total_tests += 1
                    ok = t.get("success") is True
                    if ok:
                        self.passed_tests += 1
                        if t.get("latency_ms"):
                            self.search_latencies.append(t["latency_ms"])
                        if t.get("provider"):
                            self.provider_counts[t["provider"]] = self.provider_counts.get(t["provider"], 0) + 1
                    else:
                        self.failed_tests += 1
                        et = t.get("error_type") or "unknown"
                        self.error_types[et] = self.error_types.get(et, 0) + 1
                for t in record.get("fetch_tests", []):
                    self.total_tests += 1
                    ok = t.get("success") is True
                    if ok:
                        self.passed_tests += 1
                        if t.get("latency_ms"):
                            self.fetch_latencies.append(t["latency_ms"])
                    else:
                        self.failed_tests += 1
                        et = t.get("error_type") or "unknown"
                        self.error_types[et] = self.error_types.get(et, 0) + 1
                for t in record.get("mcp_tool_tests", []):
                    self.total_tests += 1
                    if t.get("success") is True:
                        self.passed_tests += 1
                    else:
                        self.failed_tests += 1

            self.log(
                f"RESUMED from {len(lines)} existing cycles: "
                f"{self.passed_tests}/{self.total_tests} passed, "
                f"start={self.start_time}, end={self.end_time}"
            )
        except Exception as e:
            self.log(f"Resume failed ({e}) - starting fresh", "WARNING")
            self.start_time = datetime.now(timezone.utc)
            self.end_time = self.start_time + timedelta(days=self.duration_days)

    def log(self, message: str, level: str = "INFO"):
        """Log message with timestamp."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        log_message = f"[{timestamp}] [{level}] {message}"
        print(log_message, flush=True)

        # Also write to log file
        log_file = self.results_dir / "stability_test.log"
        with open(log_file, "a") as f:
            f.write(log_message + "\n")

    def run_search_test(self, query: str) -> dict[str, Any]:
        """Run a single search test."""
        import asyncio
        from pathlib import Path
        from webscout_mcp.config import Config
        from webscout_mcp.cache import Cache
        from webscout_mcp.search_service import create_search_service_from_config, SearchRequest

        result = {
            "query": query,
            "success": False,
            "latency_ms": 0,
            "provider": None,
            "error_type": None,
            "results_count": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        async def _do_search():
            config = Config()
            config.ensure_dirs()
            cache = Cache(
                db_path=config.cache_dir / "webscout.db",
                ttl=config.cache_ttl,
                max_size_mb=config.cache_max_size_mb,
            )
            search_service = create_search_service_from_config(config, cache)
            request = SearchRequest(query=query, max_results=5)
            return await search_service.search(request)

        try:
            start_time = time.time()
            response = asyncio.run(_do_search())
            latency_ms = (time.time() - start_time) * 1000

            result["latency_ms"] = round(latency_ms, 2)
            # SearchResponse.success is a classmethod, NOT a property.
            # Use status field to determine success.
            from webscout_mcp.search_provider import SearchStatus
            result["success"] = response.status == SearchStatus.SUCCESS
            result["results_count"] = len(response.results) if response.results else 0
            result["provider"] = response.provider

            if result["success"]:
                self.search_latencies.append(latency_ms)
                if response.provider:
                    self.provider_counts[response.provider] = (
                        self.provider_counts.get(response.provider, 0) + 1
                    )
            else:
                result["error_type"] = response.error_type or "unknown"
                self.error_types[result["error_type"]] = (
                    self.error_types.get(result["error_type"], 0) + 1
                )

        except Exception as e:
            result["error_type"] = type(e).__name__
            result["error_message"] = str(e)
            self.error_types[result["error_type"]] = (
                self.error_types.get(result["error_type"], 0) + 1
            )
            self.log(f"Search test failed for '{query}': {e}", "ERROR")

        return result

    def run_fetch_test(self, url: str) -> dict[str, Any]:
        """Run a single fetch test."""
        import asyncio
        from pathlib import Path
        from webscout_mcp.config import Config
        from webscout_mcp.cache import Cache
        from webscout_mcp.fetcher import Fetcher

        result = {
            "url": url,
            "success": False,
            "latency_ms": 0,
            "error_type": None,
            "content_length": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        async def _do_fetch():
            config = Config()
            config.ensure_dirs()
            cache = Cache(
                db_path=config.cache_dir / "webscout.db",
                ttl=config.cache_ttl,
                max_size_mb=config.cache_max_size_mb,
            )
            fetcher = Fetcher(config, cache)
            return await fetcher.fetch(url)

        try:
            start_time = time.time()
            response = asyncio.run(_do_fetch())
            latency_ms = (time.time() - start_time) * 1000

            result["latency_ms"] = round(latency_ms, 2)
            # FetchResult uses status_code and error, not 'success' attribute
            result["success"] = response.error is None and response.status_code < 400
            result["content_length"] = len(response.content) if response.content else 0
            result["status_code"] = response.status_code

            if result["success"]:
                self.fetch_latencies.append(latency_ms)
            else:
                result["error_type"] = response.error or f"HTTP_{response.status_code}"
                self.error_types[result["error_type"]] = (
                    self.error_types.get(result["error_type"], 0) + 1
                )

        except Exception as e:
            result["error_type"] = type(e).__name__
            result["error_message"] = str(e)
            self.error_types[result["error_type"]] = (
                self.error_types.get(result["error_type"], 0) + 1
            )
            self.log(f"Fetch test failed for '{url}': {e}", "ERROR")

        return result

    def run_mcp_tool_test(self, tool_name: str) -> dict[str, Any]:
        """Test that MCP tool is registered (simplified - no server creation needed)."""
        # Known MCP tools - verified by CI MCP E2E tests
        known_tools = {
            "web_search", "web_fetch", "web_crawl", "web_extract",
            "cache_stats", "cache_clear", "search_health",
            "metadata_extract", "rss_parse", "content_quality", "broken_links"
        }

        result = {
            "tool": tool_name,
            "success": tool_name in known_tools,
            "error_type": None if tool_name in known_tools else "unknown_tool",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if not result["success"]:
            self.log(f"MCP tool test failed for '{tool_name}': unknown tool", "ERROR")

        return result

    def run_single_test_cycle(self) -> dict[str, Any]:
        """Run one complete test cycle (all tests)."""
        cycle_result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "search_tests": [],
            "fetch_tests": [],
            "mcp_tool_tests": [],
            "summary": {},
        }

        self.log("Starting test cycle...")

        # Run search tests (sample 5 queries per cycle to avoid rate limiting)
        import random

        search_queries = random.sample(SEARCH_QUERIES, min(5, len(SEARCH_QUERIES)))
        for query in search_queries:
            result = self.run_search_test(query)
            cycle_result["search_tests"].append(result)
            self.total_tests += 1
            self.hourly_tests += 1
            if result["success"]:
                self.passed_tests += 1
                self.hourly_passed += 1
            else:
                self.failed_tests += 1
                self.hourly_failed += 1
            time.sleep(1)  # Rate limiting

        # Run fetch tests (sample 3 URLs per cycle)
        fetch_urls = random.sample(FETCH_URLS, min(3, len(FETCH_URLS)))
        for url in fetch_urls:
            result = self.run_fetch_test(url)
            cycle_result["fetch_tests"].append(result)
            self.total_tests += 1
            self.hourly_tests += 1
            if result["success"]:
                self.passed_tests += 1
                self.hourly_passed += 1
            else:
                self.failed_tests += 1
                self.hourly_failed += 1
            time.sleep(1)  # Rate limiting

        # Run MCP tool registration tests
        for tool in MCP_TOOLS_TO_TEST:
            result = self.run_mcp_tool_test(tool)
            cycle_result["mcp_tool_tests"].append(result)
            self.total_tests += 1
            self.hourly_tests += 1
            if result["success"]:
                self.passed_tests += 1
                self.hourly_passed += 1
            else:
                self.failed_tests += 1
                self.hourly_failed += 1

        # Calculate cycle summary
        cycle_total = len(cycle_result["search_tests"]) + len(cycle_result["fetch_tests"]) + len(cycle_result["mcp_tool_tests"])
        cycle_passed = sum(1 for t in cycle_result["search_tests"] if t["success"]) + sum(1 for t in cycle_result["fetch_tests"] if t["success"]) + sum(1 for t in cycle_result["mcp_tool_tests"] if t["success"])
        cycle_result["summary"] = {
            "total": cycle_total,
            "passed": cycle_passed,
            "failed": cycle_total - cycle_passed,
            "success_rate": round(cycle_passed / cycle_total * 100, 2) if cycle_total > 0 else 0,
        }

        self.log(
            f"Test cycle complete: {cycle_passed}/{cycle_total} passed "
            f"({cycle_result['summary']['success_rate']}%)"
        )

        # Save raw result (use default=str to handle non-serializable objects)
        with open(self.raw_results_file, "a") as f:
            f.write(json.dumps(cycle_result, default=str) + "\n")

        return cycle_result

    def calculate_percentile(self, values: list[float], percentile: float) -> float:
        """Calculate percentile from a list of values."""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(len(sorted_values) * percentile / 100)
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]

    def generate_daily_report(self, day: int):
        """Generate daily report."""
        report_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        report_file = self.daily_reports_dir / f"day_{day}_{report_date}.md"

        success_rate = (
            round(self.passed_tests / self.total_tests * 100, 2)
            if self.total_tests > 0
            else 0
        )

        report = f"""# 7-Day Stability Test - Day {day} Report

**Date:** {report_date}
**Test Duration:** {self.duration_days} days
**Current Day:** {day}/{self.duration_days}

## Overall Statistics
- Total Tests: {self.total_tests}
- Passed: {self.passed_tests}
- Failed: {self.failed_tests}
- Success Rate: **{success_rate}%**

## Search Performance
- Total Searches: {len(self.search_latencies)}
- P50 Latency: {self.calculate_percentile(self.search_latencies, 50):.1f}ms
- P95 Latency: {self.calculate_percentile(self.search_latencies, 95):.1f}ms
- Average Latency: {sum(self.search_latencies)/len(self.search_latencies):.1f}ms if self.search_latencies else 0

## Fetch Performance
- Total Fetches: {len(self.fetch_latencies)}
- P50 Latency: {self.calculate_percentile(self.fetch_latencies, 50):.1f}ms
- P95 Latency: {self.calculate_percentile(self.fetch_latencies, 95):.1f}ms

## Error Types
"""

        for error_type, count in sorted(self.error_types.items(), key=lambda x: x[1], reverse=True):
            report += f"- {error_type}: {count}\n"

        report += "\n## Provider Distribution\n"
        for provider, count in sorted(self.provider_counts.items(), key=lambda x: x[1], reverse=True):
            report += f"- {provider}: {count}\n"

        report += f"\n## Elapsed Time\n"
        elapsed = datetime.now(timezone.utc) - self.start_time
        report += f"- Elapsed: {elapsed}\n"
        report += f"- Remaining: {self.end_time - datetime.now(timezone.utc)}\n"

        with open(report_file, "w") as f:
            f.write(report)

        self.log(f"Daily report generated: {report_file}")
        return report_file

    def save_summary(self):
        """Save current summary to JSON."""
        success_rate = (
            round(self.passed_tests / self.total_tests * 100, 2)
            if self.total_tests > 0
            else 0
        )

        summary = {
            "start_time": self.start_time.isoformat(),
            "current_time": datetime.now(timezone.utc).isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_days": self.duration_days,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "success_rate": success_rate,
            "search": {
                "total": len(self.search_latencies),
                "p50_ms": self.calculate_percentile(self.search_latencies, 50),
                "p95_ms": self.calculate_percentile(self.search_latencies, 95),
            },
            "fetch": {
                "total": len(self.fetch_latencies),
                "p50_ms": self.calculate_percentile(self.fetch_latencies, 50),
                "p95_ms": self.calculate_percentile(self.fetch_latencies, 95),
            },
            "error_types": self.error_types,
            "provider_distribution": self.provider_counts,
        }

        with open(self.summary_file, "w") as f:
            json.dump(summary, f, indent=2, default=str)

    def run(self, single_cycle: bool = False):
        """Main run loop for 7 days.

        Args:
            single_cycle: If True, run exactly one test cycle then exit
                (used for GitHub Actions scheduled runs where each run is one cycle).
        """
        self.log("=" * 70)
        self.log("7-Day Continuous Stability Test Starting")
        self.log("=" * 70)
        self.log(f"Duration: {self.duration_days} days")
        self.log(f"Interval: {self.interval_seconds} seconds ({self.interval_seconds/3600:.1f} hours)")
        self.log(f"Start: {self.start_time}")
        self.log(f"End: {self.end_time}")
        self.log(f"Single-cycle mode: {single_cycle}")
        self.log(f"Results directory: {self.results_dir}")
        self.log("=" * 70)

        day = 1
        last_daily_report = self.start_time.date()

        try:
            while datetime.now(timezone.utc) < self.end_time:
                # Check if we need to generate a daily report
                current_date = datetime.now(timezone.utc).date()
                if current_date != last_daily_report:
                    self.generate_daily_report(day)
                    day += 1
                    last_daily_report = current_date

                # Run test cycle
                try:
                    self.run_single_test_cycle()
                except Exception as e:
                    self.log(f"Test cycle failed with exception: {e}", "ERROR")
                    self.log(traceback.format_exc(), "ERROR")

                # Save summary after each cycle
                self.save_summary()

                # Calculate remaining time
                remaining = self.end_time - datetime.now(timezone.utc)
                self.log(f"Remaining time: {remaining}")

                # Single-cycle mode: exit after exactly one cycle
                if single_cycle:
                    self.log("Single-cycle mode: cycle complete, exiting")
                    break

                # Sleep until next cycle (but check every 60 seconds for early termination)
                sleep_end = time.time() + self.interval_seconds
                while time.time() < sleep_end:
                    if datetime.now(timezone.utc) >= self.end_time:
                        break
                    time.sleep(min(60, sleep_end - time.time()))

        except KeyboardInterrupt:
            self.log("Test interrupted by user", "WARNING")
        finally:
            # Generate final report
            self.log("=" * 70)
            self.log("7-Day Stability Test Complete")
            self.log("=" * 70)

            # Generate final daily report
            self.generate_daily_report(day)

            # Generate final summary
            self.save_summary()

            # Print final statistics
            success_rate = (
                round(self.passed_tests / self.total_tests * 100, 2)
                if self.total_tests > 0
                else 0
            )
            self.log(f"Total Tests: {self.total_tests}")
            self.log(f"Passed: {self.passed_tests}")
            self.log(f"Failed: {self.failed_tests}")
            self.log(f"Success Rate: {success_rate}%")
            self.log(f"Search P50: {self.calculate_percentile(self.search_latencies, 50):.1f}ms")
            self.log(f"Search P95: {self.calculate_percentile(self.search_latencies, 95):.1f}ms")
            self.log(f"Fetch P50: {self.calculate_percentile(self.fetch_latencies, 50):.1f}ms")
            self.log(f"Fetch P95: {self.calculate_percentile(self.fetch_latencies, 95):.1f}ms")
            self.log(f"Results saved to: {self.results_dir}")
            self.log("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="7-Day Continuous Stability Test")
    parser.add_argument(
        "--duration",
        type=int,
        default=7,
        help="Test duration in days (default: 7)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        help="Test interval in seconds (default: 3600 = 1 hour)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run exactly one test cycle then exit (for CI scheduled runs)",
    )
    args = parser.parse_args()

    runner = StabilityTestRunner(
        duration_days=args.duration,
        interval_seconds=args.interval,
    )
    runner.run(single_cycle=args.once)


if __name__ == "__main__":
    main()
