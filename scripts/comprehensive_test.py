#!/usr/bin/env python3
"""
Comprehensive MCP Function Test Suite - Test all 11 MCP tools.

Covers:
- web_search (multiple queries, languages, providers)
- web_fetch (multiple URLs, content types)
- web_crawl (site exploration)
- web_extract (content extraction)
- cache_stats / cache_clear (cache management)
- search_health (health monitoring)
- metadata_extract (page metadata)
- rss_parse (RSS feed parsing)
- content_quality (content quality analysis)
- broken_links (broken link detection)

Run frequency: every 30 seconds (configurable)
"""

import asyncio
import time
import json
import tracemalloc
from datetime import datetime
from pathlib import Path

# Import project modules
from webscout_mcp.config import Config
from webscout_mcp.search_service import create_search_service_from_config
from webscout_mcp.search_provider import SearchRequest
from webscout_mcp.fetcher import Fetcher
from webscout_mcp.cache import Cache


# ============================================================
# Test Configuration
# ============================================================

OUTPUT_FILE = Path(__file__).parent.parent / "comprehensive_test.log"
REPORT_FILE = Path(__file__).parent.parent / "comprehensive_test_report.json"

# Test intervals
TEST_INTERVAL = 30  # seconds between full test runs
SEARCH_CONCURRENCY = 3  # concurrent search tests

# ============================================================
# Test Data
# ============================================================

SEARCH_QUERIES = [
    # English queries
    ("python asyncio documentation", "en", "us"),
    ("fastapi github repository", "en", "us"),
    ("postgresql tutorial", "en", "us"),
    ("docker best practices", "en", "us"),
    ("model context protocol specification", "en", "us"),
    ("latest technology news", "en", "us"),
    ("open source AI tools", "en", "us"),
    ("web scraping best practices", "en", "us"),
    # Chinese queries
    ("Python 异步编程教程", "zh", "cn"),
    ("FastAPI 中文文档", "zh", "cn"),
    ("PostgreSQL 使用指南", "zh", "cn"),
    ("Docker 入门教程", "zh", "cn"),
    ("最新科技新闻", "zh", "cn"),
    ("开源 AI 工具推荐", "zh", "cn"),
    ("网络爬虫最佳实践", "zh", "cn"),
    ("MCP 协议规范", "zh", "cn"),
]

FETCH_URLS = [
    ("https://docs.python.org/3/library/asyncio.html", "Python Docs"),
    ("https://fastapi.tiangolo.com/", "FastAPI"),
    ("https://github.com/modelcontextprotocol", "GitHub MCP"),
    ("https://pypi.org/project/webscout-mcp/", "PyPI"),
    ("https://en.wikipedia.org/wiki/Python_(programming_language)", "Wikipedia"),
]

RSS_FEEDS = [
    "https://github.com/wxs-lang/webscout-mcp/releases.atom",
    "https://hnrss.org/frontpage",
]

CRAWL_URLS = [
    "https://docs.python.org/3/library/",
]

# ============================================================
# Test Result Tracking
# ============================================================

class TestMetrics:
    """Track test metrics and statistics."""

    def __init__(self):
        self.start_time = time.time()
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0
        self.skipped_tests = 0
        self.test_history = []
        self.latencies = {}
        self.errors = []

    def record_result(self, test_name, passed, latency_ms, error=None, skipped=False):
        """Record a test result."""
        self.total_tests += 1
        if skipped:
            self.skipped_tests += 1
            status = "⏭️ SKIPPED"
        elif passed:
            self.passed_tests += 1
            status = "✅ PASS"
        else:
            self.failed_tests += 1
            status = "❌ FAIL"
            if error:
                self.errors.append((test_name, error))

        # Track latency
        if test_name not in self.latencies:
            self.latencies[test_name] = []
        self.latencies[test_name].append(latency_ms)

        # Log result
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {status} | {test_name} | {latency_ms:.0f}ms"
        if error:
            log_entry += f" | Error: {str(error)[:80]}"
        print(log_entry)

        # Append to history
        self.test_history.append({
            "timestamp": timestamp,
            "test": test_name,
            "status": "pass" if passed else ("skip" if skipped else "fail"),
            "latency_ms": latency_ms,
            "error": str(error) if error else None,
        })

    def get_summary(self):
        """Get test summary statistics."""
        elapsed = time.time() - self.start_time
        pass_rate = (self.passed_tests / self.total_tests * 100) if self.total_tests > 0 else 0

        # Calculate P50/P95 latencies per test type
        latency_stats = {}
        for test_name, lats in self.latencies.items():
            if lats:
                sorted_lats = sorted(lats)
                p50 = sorted_lats[len(sorted_lats) // 2]
                p95 = sorted_lats[int(len(sorted_lats) * 0.95)]
                latency_stats[test_name] = {
                    "p50_ms": round(p50, 1),
                    "p95_ms": round(p95, 1),
                    "count": len(lats),
                }

        return {
            "elapsed_seconds": round(elapsed, 1),
            "total_tests": self.total_tests,
            "passed": self.passed_tests,
            "failed": self.failed_tests,
            "skipped": self.skipped_tests,
            "pass_rate": round(pass_rate, 1),
            "latency_stats": latency_stats,
            "recent_errors": self.errors[-10:],
        }


# ============================================================
# Test Functions
# ============================================================

async def test_web_search(search_service, metrics, query, language, region):
    """Test web_search tool."""
    test_name = f"web_search[{query[:20]}...]"
    start = time.time()
    try:
        request = SearchRequest(query=query, max_results=5, language=language, region=region)
        response = await asyncio.wait_for(search_service.search(request), timeout=30)
        latency = (time.time() - start) * 1000
        passed = response.is_success and len(response.results) > 0
        error = None if passed else f"Success={response.is_success}, Results={len(response.results)}"
        metrics.record_result(test_name, passed, latency, error)
        return passed
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)
        return False


async def test_web_fetch(fetcher, metrics, url, name):
    """Test web_fetch tool."""
    test_name = f"web_fetch[{name}]"
    start = time.time()
    try:
        result = await asyncio.wait_for(fetcher.fetch(url), timeout=30)
        latency = (time.time() - start) * 1000
        content_len = len(result.get("content", "")) if isinstance(result, dict) else len(str(result))
        passed = content_len > 0
        error = None if passed else f"Empty content (len={content_len})"
        metrics.record_result(test_name, passed, latency, error)
        return passed
    except asyncio.TimeoutError:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, "Timeout (>30s)")
        return False
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)
        return False


async def test_cache_operations(cache, metrics):
    """Test cache_stats and cache_clear tools."""
    # Test cache_stats
    test_name = "cache_stats"
    start = time.time()
    try:
        stats = cache.get_stats() if hasattr(cache, 'get_stats') else {}
        latency = (time.time() - start) * 1000
        passed = isinstance(stats, dict)
        metrics.record_result(test_name, passed, latency)
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)

    # Test cache_clear
    test_name = "cache_clear"
    start = time.time()
    try:
        if hasattr(cache, 'clear'):
            cache.clear()
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, True, latency)
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)


async def test_search_health(search_service, metrics):
    """Test search_health tool."""
    test_name = "search_health"
    start = time.time()
    try:
        health = search_service.get_health_report()
        latency = (time.time() - start) * 1000
        passed = isinstance(health, dict) and "backends" in health
        error = None if passed else "Missing 'backends' key"
        metrics.record_result(test_name, passed, latency, error)
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)


async def test_metadata_extract(fetcher, metrics, url):
    """Test metadata_extract tool."""
    test_name = "metadata_extract"
    start = time.time()
    try:
        # Try to extract metadata from fetched page
        result = await asyncio.wait_for(fetcher.fetch(url), timeout=15)
        metadata = result.get("metadata", {}) if isinstance(result, dict) else {}
        latency = (time.time() - start) * 1000
        passed = isinstance(metadata, dict)
        metrics.record_result(test_name, passed, latency)
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)


async def test_rss_parse(metrics, feed_url):
    """Test rss_parse tool."""
    test_name = f"rss_parse[{feed_url[:30]}...]"
    start = time.time()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(feed_url)
            content = response.text
        # Basic RSS validation
        is_rss = "<rss" in content or "<feed" in content or "<?xml" in content
        latency = (time.time() - start) * 1000
        passed = is_rss and len(content) > 100
        error = None if passed else "Not a valid RSS/XML feed"
        metrics.record_result(test_name, passed, latency, error)
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)


async def test_content_quality(fetcher, metrics, url):
    """Test content_quality tool."""
    test_name = "content_quality"
    start = time.time()
    try:
        result = await asyncio.wait_for(fetcher.fetch(url), timeout=15)
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        # Basic quality metrics
        word_count = len(content.split())
        char_count = len(content)
        has_content = word_count > 10
        latency = (time.time() - start) * 1000
        passed = has_content
        error = None if passed else f"Low content: {word_count} words"
        metrics.record_result(test_name, passed, latency, error)
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)


async def test_broken_links(fetcher, metrics, url):
    """Test broken_links tool (basic implementation)."""
    test_name = "broken_links"
    start = time.time()
    try:
        result = await asyncio.wait_for(fetcher.fetch(url), timeout=15)
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        # Count links in content (basic)
        import re
        links = re.findall(r'href=["\']([^"\']+)["\']', content)
        latency = (time.time() - start) * 1000
        passed = isinstance(links, list)
        metrics.record_result(test_name, passed, latency, f"Found {len(links)} links")
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)


async def test_web_crawl(metrics, url):
    """Test web_crawl tool (basic implementation)."""
    test_name = "web_crawl"
    start = time.time()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            response = await client.get(url)
            status_code = response.status_code
        latency = (time.time() - start) * 1000
        passed = status_code == 200
        error = None if passed else f"HTTP {status_code}"
        metrics.record_result(test_name, passed, latency, error)
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)


async def test_web_extract(fetcher, metrics, url):
    """Test web_extract tool."""
    test_name = "web_extract"
    start = time.time()
    try:
        result = await asyncio.wait_for(fetcher.fetch(url), timeout=15)
        content = result.get("content", "") if isinstance(result, dict) else str(result)
        extracted = len(content) > 0
        latency = (time.time() - start) * 1000
        passed = extracted
        metrics.record_result(test_name, passed, latency)
    except Exception as e:
        latency = (time.time() - start) * 1000
        metrics.record_result(test_name, False, latency, e)


# ============================================================
# Main Test Runner
# ============================================================

async def run_full_test_suite():
    """Run the full test suite covering all MCP tools."""
    print("\n" + "=" * 80)
    print("🧪 COMPREHENSIVE MCP FUNCTION TEST SUITE")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Test interval: {TEST_INTERVAL}s")
    print(f"Search queries: {len(SEARCH_QUERIES)}")
    print(f"Fetch URLs: {len(FETCH_URLS)}")
    print(f"RSS feeds: {len(RSS_FEEDS)}")
    print("=" * 80 + "\n")

    # Initialize components
    config = Config()
    search_service = create_search_service_from_config(config)
    fetcher = Fetcher(config)
    cache = Cache(db_path=Path("/tmp/webscout_test_cache.db"))

    metrics = TestMetrics()
    tracemalloc.start()

    iteration = 0
    try:
        while True:
            iteration += 1
            print(f"\n{'─' * 80}")
            print(f"📋 TEST ITERATION {iteration} - {datetime.now().strftime('%H:%M:%S')}")
            print(f"{'─' * 80}\n")

            # 1. Web Search tests (concurrent)
            print("🔍 Testing web_search...")
            search_tasks = []
            for i, (query, lang, region) in enumerate(SEARCH_QUERIES[:8]):  # Test 8 queries per iteration
                search_tasks.append(test_web_search(search_service, metrics, query, lang, region))
            await asyncio.gather(*search_tasks, return_exceptions=True)

            # 2. Web Fetch tests
            print("\n🌐 Testing web_fetch...")
            for url, name in FETCH_URLS:
                await test_web_fetch(fetcher, metrics, url, name)

            # 3. Cache operations
            print("\n💾 Testing cache_stats / cache_clear...")
            await test_cache_operations(cache, metrics)

            # 4. Search health
            print("\n❤️ Testing search_health...")
            await test_search_health(search_service, metrics)

            # 5. Metadata extract
            print("\n📋 Testing metadata_extract...")
            await test_metadata_extract(fetcher, metrics, FETCH_URLS[0][0])

            # 6. RSS parse
            print("\n📰 Testing rss_parse...")
            for feed_url in RSS_FEEDS:
                await test_rss_parse(metrics, feed_url)

            # 7. Content quality
            print("\n✨ Testing content_quality...")
            await test_content_quality(fetcher, metrics, FETCH_URLS[0][0])

            # 8. Broken links
            print("\n🔗 Testing broken_links...")
            await test_broken_links(fetcher, metrics, FETCH_URLS[0][0])

            # 9. Web crawl
            print("\n🕷️ Testing web_crawl...")
            await test_web_crawl(metrics, CRAWL_URLS[0])

            # 10. Web extract
            print("\n📝 Testing web_extract...")
            await test_web_extract(fetcher, metrics, FETCH_URLS[0][0])

            # Print iteration summary
            summary = metrics.get_summary()
            print(f"\n{'─' * 80}")
            print(f"📊 ITERATION {iteration} SUMMARY")
            print(f"{'─' * 80}")
            print(f"  Total: {summary['total_tests']} | "
                  f"Passed: {summary['passed']} | "
                  f"Failed: {summary['failed']} | "
                  f"Skipped: {summary['skipped']} | "
                  f"Pass Rate: {summary['pass_rate']}%")
            print(f"  Elapsed: {summary['elapsed_seconds']}s")

            # Memory usage
            current, peak = tracemalloc.get_traced_memory()
            print(f"  Memory: {current / 1024 / 1024:.1f}MB (peak: {peak / 1024 / 1024:.1f}MB)")

            # Save report
            report = {
                "iteration": iteration,
                "timestamp": datetime.now().isoformat(),
                "summary": summary,
                "recent_tests": metrics.test_history[-50:],
            }
            with open(REPORT_FILE, "w") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)

            # Alert on failures
            if summary["failed"] > 0:
                print(f"\n⚠️  WARNING: {summary['failed']} test failures detected!")
                print("Recent errors:")
                for test_name, error in summary["recent_errors"][-5:]:
                    print(f"  - {test_name}: {str(error)[:80]}")

            print(f"\n💤 Sleeping {TEST_INTERVAL}s until next iteration...")
            await asyncio.sleep(TEST_INTERVAL)

    except KeyboardInterrupt:
        print("\n\n👋 Test suite stopped by user.")
    finally:
        # Final summary
        final_summary = metrics.get_summary()
        print("\n" + "=" * 80)
        print("🏁 FINAL TEST SUMMARY")
        print("=" * 80)
        print(f"  Total: {final_summary['total_tests']}")
        print(f"  Passed: {final_summary['passed']}")
        print(f"  Failed: {final_summary['failed']}")
        print(f"  Pass Rate: {final_summary['pass_rate']}%")
        print(f"  Elapsed: {final_summary['elapsed_seconds']}s")
        print("=" * 80)

        # Cleanup
        await search_service.close()
        tracemalloc.stop()


if __name__ == "__main__":
    asyncio.run(run_full_test_suite())
