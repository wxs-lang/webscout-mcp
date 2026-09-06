#!/usr/bin/env python3
"""
24-hour stability test for webscout-mcp.

Continuously tests web_search and web_fetch, records metrics,
and generates periodic reports.
"""

import asyncio
import json
import time
import os
import sys
import tracemalloc
from datetime import datetime, timedelta
from typing import Any

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webscout_mcp.search_service import SearchService, create_search_service_from_config
from webscout_mcp.search_provider import SearchRequest
from webscout_mcp.config import Config
from webscout_mcp.fetcher import Fetcher


# Test queries - mix of Chinese and English
SEARCH_QUERIES = [
    # English technical
    "python asyncio documentation",
    "fastapi github repository",
    "postgresql tutorial",
    "docker best practices",
    "model context protocol specification",
    # English general
    "latest technology news",
    "open source AI tools",
    "web scraping best practices",
    # Chinese technical
    "Python 异步编程教程",
    "FastAPI 中文文档",
    "PostgreSQL 使用指南",
    "Docker 入门教程",
    # Chinese general
    "最新科技新闻",
    "开源 AI 工具推荐",
    "网络爬虫最佳实践",
    "考研数学复习资料",
]

# Test URLs for fetch
FETCH_URLS = [
    "https://docs.python.org/3/library/asyncio.html",
    "https://fastapi.tiangolo.com/",
    "https://github.com/modelcontextprotocol",
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "https://pypi.org/project/webscout-mcp/",
]


class StabilityMetrics:
    """Track stability metrics over time."""

    def __init__(self):
        self.start_time = time.time()
        self.search_total = 0
        self.search_success = 0
        self.search_failed = 0
        self.search_latencies = []
        self.search_errors = {}

        self.fetch_total = 0
        self.fetch_success = 0
        self.fetch_failed = 0
        self.fetch_latencies = []
        self.fetch_errors = {}

        self.provider_stats = {}
        self.memory_snapshots = []

    def record_search(self, success: bool, latency_ms: float, provider: str = "unknown", error: str = None):
        self.search_total += 1
        self.search_latencies.append(latency_ms)
        if success:
            self.search_success += 1
        else:
            self.search_failed += 1
            if error:
                self.search_errors[error] = self.search_errors.get(error, 0) + 1

        if provider not in self.provider_stats:
            self.provider_stats[provider] = {"total": 0, "success": 0, "failed": 0}
        self.provider_stats[provider]["total"] += 1
        if success:
            self.provider_stats[provider]["success"] += 1
        else:
            self.provider_stats[provider]["failed"] += 1

    def record_fetch(self, success: bool, latency_ms: float, error: str = None):
        self.fetch_total += 1
        self.fetch_latencies.append(latency_ms)
        if success:
            self.fetch_success += 1
        else:
            self.fetch_failed += 1
            if error:
                self.fetch_errors[error] = self.fetch_errors.get(error, 0) + 1

    def record_memory(self, memory_mb: float):
        self.memory_snapshots.append((time.time(), memory_mb))

    def get_stats(self) -> dict[str, Any]:
        elapsed = time.time() - self.start_time
        hours = elapsed / 3600

        def p50(latencies):
            if not latencies:
                return 0
            sorted_l = sorted(latencies)
            return sorted_l[len(sorted_l) // 2]

        def p95(latencies):
            if not latencies:
                return 0
            sorted_l = sorted(latencies)
            idx = int(len(sorted_l) * 0.95)
            return sorted_l[min(idx, len(sorted_l) - 1)]

        return {
            "elapsed_hours": round(hours, 2),
            "search": {
                "total": self.search_total,
                "success": self.search_success,
                "failed": self.search_failed,
                "success_rate": round(self.search_success / self.search_total * 100, 1) if self.search_total > 0 else 0,
                "p50_ms": round(p50(self.search_latencies), 1),
                "p95_ms": round(p95(self.search_latencies), 1),
                "errors": dict(sorted(self.search_errors.items(), key=lambda x: -x[1])[:10]),
            },
            "fetch": {
                "total": self.fetch_total,
                "success": self.fetch_success,
                "failed": self.fetch_failed,
                "success_rate": round(self.fetch_success / self.fetch_total * 100, 1) if self.fetch_total > 0 else 0,
                "p50_ms": round(p50(self.fetch_latencies), 1),
                "p95_ms": round(p95(self.fetch_latencies), 1),
                "errors": dict(sorted(self.fetch_errors.items(), key=lambda x: -x[1])[:10]),
            },
            "providers": self.provider_stats,
            "requests_per_hour": round((self.search_total + self.fetch_total) / hours, 1) if hours > 0 else 0,
        }


async def run_search_test(search_service: SearchService, metrics: StabilityMetrics, query: str):
    """Run a single search test."""
    start = time.time()
    try:
        request = SearchRequest(query=query, max_results=5)
        result = await search_service.search(request)
        latency = (time.time() - start) * 1000
        provider = getattr(result, 'provider', 'unknown')
        success = result.is_success if hasattr(result, 'is_success') else getattr(result, 'status') == 'success'
        error = getattr(result, 'error_type', None) if not success else None
        metrics.record_search(success, latency, provider, str(error) if error else None)

        status = "✅" if success else "❌"
        result_count = len(getattr(result, 'results', [])) if success else 0
        print(f"  {status} Search: {query[:40]:40s} | {latency:6.0f}ms | {provider} | {result_count} results")
        return success
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_search(False, latency, "exception", str(type(e).__name__))
        print(f"  ❌ Search: {query[:40]:40s} | {latency:6.0f}ms | EXCEPTION: {type(e).__name__}: {str(e)[:80]}")
        return False


async def run_fetch_test(fetcher: Fetcher, metrics: StabilityMetrics, url: str):
    """Run a single fetch test."""
    start = time.time()
    try:
        result = await fetcher.fetch(url)
        latency = (time.time() - start) * 1000
        success = result is not None and getattr(result, 'success', True)
        error = None if success else "fetch_failed"
        metrics.record_fetch(success, latency, error)

        status = "✅" if success else "❌"
        content_len = len(getattr(result, 'content', '')) if result else 0
        print(f"  {status} Fetch:  {url[:50]:50s} | {latency:6.0f}ms | {content_len} chars")
        return success
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_fetch(False, latency, str(type(e).__name__))
        print(f"  ❌ Fetch:  {url[:50]:50s} | {latency:6.0f}ms | EXCEPTION: {type(e).__name__}")
        return False


def print_report(metrics: StabilityMetrics, iteration: int):
    """Print periodic stability report."""
    stats = metrics.get_stats()
    print("\n" + "=" * 80)
    print(f"📊 STABILITY REPORT - Iteration {iteration} | Elapsed: {stats['elapsed_hours']}h")
    print("=" * 80)
    print(f"  Search: {stats['search']['success']}/{stats['search']['total']} "
          f"({stats['search']['success_rate']}%) | "
          f"P50: {stats['search']['p50_ms']}ms | P95: {stats['search']['p95_ms']}ms")
    print(f"  Fetch:  {stats['fetch']['success']}/{stats['fetch']['total']} "
          f"({stats['fetch']['success_rate']}%) | "
          f"P50: {stats['fetch']['p50_ms']}ms | P95: {stats['fetch']['p95_ms']}ms")
    print(f"  Rate:   {stats['requests_per_hour']} requests/hour")

    if stats['search']['errors']:
        print(f"  Search errors: {stats['search']['errors']}")
    if stats['fetch']['errors']:
        print(f"  Fetch errors: {stats['fetch']['errors']}")

    print("=" * 80 + "\n")

    # Save report to file
    report_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stability_report.json")
    with open(report_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "iteration": iteration,
            "stats": stats,
        }, f, indent=2, ensure_ascii=False)


async def main():
    """Main stability test loop."""
    print("=" * 80)
    print("🚀 webscout-mcp 24-Hour Stability Test")
    print("=" * 80)
    print(f"Start time: {datetime.now().isoformat()}")
    print(f"Test duration: 24 hours")
    print(f"Search queries: {len(SEARCH_QUERIES)}")
    print(f"Fetch URLs: {len(FETCH_URLS)}")
    print("=" * 80 + "\n")

    # Initialize components
    config = Config()
    search_service = create_search_service_from_config(config)
    fetcher = Fetcher(config=config)
    metrics = StabilityMetrics()

    # Start memory tracking
    tracemalloc.start()

    iteration = 0
    max_iterations = 24 * 60  # 24 hours, one iteration per minute (approx)
    report_interval = 10  # Report every 10 iterations

    try:
        while iteration < max_iterations:
            iteration += 1
            print(f"\n--- Iteration {iteration} ({datetime.now().strftime('%H:%M:%S')}) ---")

            # Run searches (rotate through queries)
            query_idx = (iteration - 1) % len(SEARCH_QUERIES)
            await run_search_test(search_service, metrics, SEARCH_QUERIES[query_idx])

            # Run fetch every 3 iterations
            if iteration % 3 == 0:
                url_idx = (iteration // 3 - 1) % len(FETCH_URLS)
                await run_fetch_test(fetcher, metrics, FETCH_URLS[url_idx])

            # Record memory
            current, peak = tracemalloc.get_traced_memory()
            metrics.record_memory(current / 1024 / 1024)

            # Print periodic report
            if iteration % report_interval == 0:
                print_report(metrics, iteration)

            # Wait before next iteration (with jitter to avoid thundering herd)
            await asyncio.sleep(55 + (iteration % 10))  # ~1 minute per iteration

    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Fatal error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Final report
        print("\n" + "=" * 80)
        print("🏁 FINAL STABILITY REPORT")
        print("=" * 80)
        print_report(metrics, iteration)

        tracemalloc.stop()

        # Save final results
        final_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stability_final.json")
        with open(final_file, 'w') as f:
            json.dump({
                "end_time": datetime.now().isoformat(),
                "total_iterations": iteration,
                "final_stats": metrics.get_stats(),
            }, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Results saved to: {final_file}")


if __name__ == "__main__":
    asyncio.run(main())
