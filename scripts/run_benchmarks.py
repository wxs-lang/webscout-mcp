#!/usr/bin/env python3
"""
Performance Benchmark Report Generator for webscout-mcp

This script runs performance benchmarks and generates a detailed report.
It can be used in CI/CD pipelines to track performance over time.

Usage:
    python scripts/run_benchmarks.py
    python scripts/run_benchmarks.py --output report.md
    python scripts/run_benchmarks.py --json
    python scripts/run_benchmarks.py --compare previous.json
"""

import sys
import os
import time
import json
import statistics
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class BenchmarkResult:
    """Stores the result of a single benchmark."""

    def __init__(self, name: str, durations: List[float], metadata: Optional[Dict] = None):
        self.name = name
        self.durations = durations
        self.metadata = metadata or {}
        self.iterations = len(durations)

    @property
    def min_ms(self) -> float:
        return min(self.durations)

    @property
    def max_ms(self) -> float:
        return max(self.durations)

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.durations)

    @property
    def median_ms(self) -> float:
        return statistics.median(self.durations)

    @property
    def stdev_ms(self) -> float:
        return statistics.stdev(self.durations) if len(self.durations) > 1 else 0

    @property
    def p95_ms(self) -> float:
        sorted_durations = sorted(self.durations)
        index = int(len(sorted_durations) * 0.95)
        return sorted_durations[min(index, len(sorted_durations) - 1)]

    @property
    def p99_ms(self) -> float:
        sorted_durations = sorted(self.durations)
        index = int(len(sorted_durations) * 0.99)
        return sorted_durations[min(index, len(sorted_durations) - 1)]

    @property
    def total_ms(self) -> float:
        return sum(self.durations)

    @property
    def throughput_per_sec(self) -> float:
        return self.iterations / (self.total_ms / 1000) if self.total_ms > 0 else 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "min_ms": round(self.min_ms, 3),
            "max_ms": round(self.max_ms, 3),
            "mean_ms": round(self.mean_ms, 3),
            "median_ms": round(self.median_ms, 3),
            "stdev_ms": round(self.stdev_ms, 3),
            "p95_ms": round(self.p95_ms, 3),
            "p99_ms": round(self.p99_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "throughput_per_sec": round(self.throughput_per_sec, 2),
            "metadata": self.metadata,
        }


class BenchmarkRunner:
    """Runs performance benchmarks and collects results."""

    def __init__(self, warmup_iterations: int = 3, default_iterations: int = 20):
        self.warmup_iterations = warmup_iterations
        self.default_iterations = default_iterations
        self.results: List[BenchmarkResult] = []

    def run_benchmark(
        self,
        name: str,
        func,
        iterations: Optional[int] = None,
        metadata: Optional[Dict] = None,
    ) -> BenchmarkResult:
        """Run a single benchmark.

        Args:
            name: Name of the benchmark.
            func: Function to benchmark.
            iterations: Number of iterations.
            metadata: Additional metadata.

        Returns:
            BenchmarkResult with statistics.
        """
        iterations = iterations or self.default_iterations

        # Warmup
        for _ in range(self.warmup_iterations):
            try:
                func()
            except Exception:
                pass

        # Benchmark
        durations = []
        for _ in range(iterations):
            try:
                start = time.perf_counter()
                func()
                end = time.perf_counter()
                durations.append((end - start) * 1000)  # ms
            except Exception as e:
                print(f"  [WARN] Benchmark '{name}' iteration failed: {e}")

        if not durations:
            print(f"  [ERROR] Benchmark '{name}' all iterations failed")
            return BenchmarkResult(name, [0], metadata or {"error": "all iterations failed"})

        result = BenchmarkResult(name, durations, metadata)
        self.results.append(result)
        return result

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all benchmarks."""
        return {
            "timestamp": datetime.now().isoformat(),
            "total_benchmarks": len(self.results),
            "benchmarks": [r.to_dict() for r in self.results],
            "system_info": self._get_system_info(),
        }

    def _get_system_info(self) -> Dict[str, Any]:
        """Get system information."""
        info = {
            "python_version": sys.version,
            "platform": sys.platform,
        }

        try:
            import platform
            info["system"] = platform.system()
            info["release"] = platform.release()
            info["machine"] = platform.machine()
            info["processor"] = platform.processor()
        except Exception:
            pass

        try:
            import psutil
            info["cpu_count"] = psutil.cpu_count()
            info["memory_total_gb"] = round(psutil.virtual_memory().total / (1024 ** 3), 2)
        except Exception:
            pass

        return info


def run_search_benchmarks(runner: BenchmarkRunner):
    """Run search-related benchmarks."""
    print("\n📊 Running Search Benchmarks...")

    try:
        from webscout_mcp.search_optimizer import SearchOptimizer

        optimizer = SearchOptimizer(backends=["mock"], enable_cache=False)

        def mock_search(backend, query, max_results):
            return [
                {"title": f"Result {i}", "url": f"https://example.com/page{i}", "snippet": f"Snippet {i}"}
                for i in range(10)
            ]

        runner.run_benchmark(
            "search_optimizer_basic",
            lambda: optimizer.search("test query", search_fn=mock_search),
            iterations=50,
            metadata={"category": "search", "description": "Basic search with mock backend"},
        )

        # With caching
        optimizer_cached = SearchOptimizer(backends=["mock"], enable_cache=True, cache_ttl=3600)
        # First call to populate cache
        optimizer_cached.search("cached query", search_fn=mock_search)

        runner.run_benchmark(
            "search_optimizer_cached",
            lambda: optimizer_cached.search("cached query", search_fn=mock_search),
            iterations=100,
            metadata={"category": "search", "description": "Search with cache hit"},
        )

    except Exception as e:
        print(f"  [ERROR] Search benchmarks failed: {e}")


def run_content_extraction_benchmarks(runner: BenchmarkRunner):
    """Run content extraction benchmarks."""
    print("\n📊 Running Content Extraction Benchmarks...")

    try:
        from webscout_mcp.content_extractor import ContentExtractor

        extractor = ContentExtractor(enable_multi_algorithm=True)

        sample_html = """
        <!DOCTYPE html>
        <html><head><title>Test Page</title></head>
        <body>
        <article>
        <h1>Test Article</h1>
        <p>This is a test article with some content.</p>
        <p>More content here for testing purposes.</p>
        <h2>Section 1</h2>
        <p>Section content goes here.</p>
        </article>
        </body></html>
        """

        runner.run_benchmark(
            "content_extractor_basic",
            lambda: extractor.extract(sample_html, url="https://example.com"),
            iterations=30,
            metadata={"category": "extraction", "description": "Basic content extraction"},
        )

    except Exception as e:
        print(f"  [ERROR] Content extraction benchmarks failed: {e}")


def run_security_benchmarks(runner: BenchmarkRunner):
    """Run security-related benchmarks."""
    print("\n📊 Running Security Benchmarks...")

    try:
        from webscout_mcp.security import SensitiveDataFilter, InputValidator, SSRFProtector

        # Sensitive data filtering
        filter_obj = SensitiveDataFilter()
        test_text = "API key: abc123, password: secret456, email: user@example.com, credit card: 4111-1111-1111-1111"

        runner.run_benchmark(
            "security_sensitive_filter",
            lambda: filter_obj.mask(test_text),
            iterations=200,
            metadata={"category": "security", "description": "Sensitive data filtering"},
        )

        # Input validation
        validator = InputValidator()

        runner.run_benchmark(
            "security_url_validation",
            lambda: validator.validate_url("https://example.com/path?query=value"),
            iterations=500,
            metadata={"category": "security", "description": "URL validation"},
        )

        # SSRF protection
        protector = SSRFProtector(dns_resolution=False)

        runner.run_benchmark(
            "security_ssrf_protection",
            lambda: protector.validate_url("https://example.com/page"),
            iterations=200,
            metadata={"category": "security", "description": "SSRF URL validation"},
        )

    except Exception as e:
        print(f"  [ERROR] Security benchmarks failed: {e}")


def run_architecture_benchmarks(runner: BenchmarkRunner):
    """Run architecture-related benchmarks."""
    print("\n📊 Running Architecture Benchmarks...")

    try:
        from webscout_mcp.architecture import EventBus, DIContainer

        # Event bus
        bus = EventBus()
        bus.subscribe("test.event", lambda e: None)

        runner.run_benchmark(
            "architecture_event_publish",
            lambda: bus.publish("test.event", data={"key": "value"}),
            iterations=1000,
            metadata={"category": "architecture", "description": "Event bus publish"},
        )

        # Multiple handlers
        bus_multi = EventBus()
        for i in range(10):
            bus_multi.subscribe("test.event", lambda e, i=i: None)

        runner.run_benchmark(
            "architecture_event_multi_handler",
            lambda: bus_multi.publish("test.event"),
            iterations=500,
            metadata={"category": "architecture", "description": "Event bus with 10 handlers"},
        )

        # DI container
        container = DIContainer()
        container.register_singleton("service", {"value": "test"})

        runner.run_benchmark(
            "architecture_di_resolve",
            lambda: container.resolve("service"),
            iterations=1000,
            metadata={"category": "architecture", "description": "DI container resolve"},
        )

    except Exception as e:
        print(f"  [ERROR] Architecture benchmarks failed: {e}")


def run_health_benchmarks(runner: BenchmarkRunner):
    """Run health check benchmarks."""
    print("\n📊 Running Health Check Benchmarks...")

    try:
        from webscout_mcp.health import HealthChecker, SystemMonitor

        # Health checker
        checker = HealthChecker(version="0.4.0")
        checker.register_check("test", lambda: (True, "ok"))

        runner.run_benchmark(
            "health_liveness_check",
            lambda: checker.check_liveness(),
            iterations=200,
            metadata={"category": "health", "description": "Liveness check"},
        )

        runner.run_benchmark(
            "health_readiness_check",
            lambda: checker.check_readiness(),
            iterations=100,
            metadata={"category": "health", "description": "Readiness check"},
        )

        # System monitor
        monitor = SystemMonitor()

        runner.run_benchmark(
            "health_system_metrics",
            lambda: monitor.collect_metrics(),
            iterations=50,
            metadata={"category": "health", "description": "System metrics collection"},
        )

    except Exception as e:
        print(f"  [ERROR] Health benchmarks failed: {e}")


def generate_markdown_report(summary: Dict[str, Any], output_path: str):
    """Generate a markdown report from benchmark results."""
    lines = []

    lines.append("# Performance Benchmark Report")
    lines.append("")
    lines.append(f"**Generated:** {summary['timestamp']}")
    lines.append(f"**Total Benchmarks:** {summary['total_benchmarks']}")
    lines.append("")

    # System info
    lines.append("## System Information")
    lines.append("")
    sys_info = summary.get("system_info", {})
    lines.append(f"- **Python:** {sys_info.get('python_version', 'N/A')}")
    lines.append(f"- **Platform:** {sys_info.get('platform', 'N/A')}")
    lines.append(f"- **System:** {sys_info.get('system', 'N/A')}")
    lines.append(f"- **CPU Count:** {sys_info.get('cpu_count', 'N/A')}")
    lines.append(f"- **Memory:** {sys_info.get('memory_total_gb', 'N/A')} GB")
    lines.append("")

    # Results by category
    lines.append("## Benchmark Results")
    lines.append("")

    categories = {}
    for bench in summary["benchmarks"]:
        category = bench.get("metadata", {}).get("category", "other")
        if category not in categories:
            categories[category] = []
        categories[category].append(bench)

    for category, benches in categories.items():
        lines.append(f"### {category.title()}")
        lines.append("")
        lines.append("| Benchmark | Iterations | Mean (ms) | P95 (ms) | P99 (ms) | Throughput (ops/s) |")
        lines.append("|-----------|------------|-----------|----------|----------|---------------------|")

        for bench in benches:
            lines.append(
                f"| {bench['name']} | {bench['iterations']} | {bench['mean_ms']:.3f} | "
                f"{bench['p95_ms']:.3f} | {bench['p99_ms']:.3f} | {bench['throughput_per_sec']:.2f} |"
            )

        lines.append("")

    # Detailed results
    lines.append("## Detailed Results")
    lines.append("")

    for bench in summary["benchmarks"]:
        lines.append(f"### {bench['name']}")
        lines.append("")
        if bench.get("metadata", {}).get("description"):
            lines.append(f"**Description:** {bench['metadata']['description']}")
            lines.append("")
        lines.append(f"- **Iterations:** {bench['iterations']}")
        lines.append(f"- **Min:** {bench['min_ms']:.3f} ms")
        lines.append(f"- **Max:** {bench['max_ms']:.3f} ms")
        lines.append(f"- **Mean:** {bench['mean_ms']:.3f} ms")
        lines.append(f"- **Median:** {bench['median_ms']:.3f} ms")
        lines.append(f"- **Std Dev:** {bench['stdev_ms']:.3f} ms")
        lines.append(f"- **P95:** {bench['p95_ms']:.3f} ms")
        lines.append(f"- **P99:** {bench['p99_ms']:.3f} ms")
        lines.append(f"- **Total:** {bench['total_ms']:.3f} ms")
        lines.append(f"- **Throughput:** {bench['throughput_per_sec']:.2f} ops/s")
        lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(f"Total benchmarks run: **{summary['total_benchmarks']}**")
    lines.append("")
    lines.append("---")
    lines.append("*Report generated by webscout-mcp benchmark tool*")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n📄 Markdown report saved to: {output_path}")


def compare_reports(current: Dict, previous: Dict) -> Dict:
    """Compare two benchmark reports and identify regressions."""
    comparisons = []
    regressions = []
    improvements = []

    current_benches = {b["name"]: b for b in current["benchmarks"]}
    previous_benches = {b["name"]: b for b in previous.get("benchmarks", [])}

    for name, current_bench in current_benches.items():
        if name in previous_benches:
            previous_bench = previous_benches[name]
            mean_diff = current_bench["mean_ms"] - previous_bench["mean_ms"]
            mean_pct = (mean_diff / previous_bench["mean_ms"]) * 100 if previous_bench["mean_ms"] > 0 else 0

            comparison = {
                "name": name,
                "previous_mean_ms": previous_bench["mean_ms"],
                "current_mean_ms": current_bench["mean_ms"],
                "difference_ms": round(mean_diff, 3),
                "difference_pct": round(mean_pct, 2),
                "status": "regression" if mean_pct > 10 else ("improvement" if mean_pct < -10 else "stable"),
            }
            comparisons.append(comparison)

            if comparison["status"] == "regression":
                regressions.append(comparison)
            elif comparison["status"] == "improvement":
                improvements.append(comparison)

    return {
        "comparisons": comparisons,
        "regressions": regressions,
        "improvements": improvements,
        "total_comparisons": len(comparisons),
        "total_regressions": len(regressions),
        "total_improvements": len(improvements),
    }


def main():
    parser = argparse.ArgumentParser(description="Run performance benchmarks for webscout-mcp")
    parser.add_argument("--output", "-o", default="benchmark_report.md", help="Output file path")
    parser.add_argument("--json", action="store_true", help="Output JSON format")
    parser.add_argument("--compare", help="Path to previous benchmark JSON for comparison")
    parser.add_argument("--iterations", type=int, default=20, help="Default iterations per benchmark")
    parser.add_argument("--warmup", type=int, default=3, help="Warmup iterations")
    parser.add_argument("--skip", nargs="*", default=[], help="Benchmark categories to skip")

    args = parser.parse_args()

    print("=" * 60)
    print("webscout-mcp Performance Benchmarks")
    print("=" * 60)

    runner = BenchmarkRunner(
        warmup_iterations=args.warmup,
        default_iterations=args.iterations,
    )

    # Run benchmarks
    if "search" not in args.skip:
        run_search_benchmarks(runner)
    if "extraction" not in args.skip:
        run_content_extraction_benchmarks(runner)
    if "security" not in args.skip:
        run_security_benchmarks(runner)
    if "architecture" not in args.skip:
        run_architecture_benchmarks(runner)
    if "health" not in args.skip:
        run_health_benchmarks(runner)

    # Get summary
    summary = runner.get_summary()

    # Output
    if args.json:
        json_path = args.output.replace(".md", ".json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\n📄 JSON report saved to: {json_path}")
    else:
        generate_markdown_report(summary, args.output)

    # Comparison
    if args.compare:
        try:
            with open(args.compare, "r", encoding="utf-8") as f:
                previous = json.load(f)

            comparison = compare_reports(summary, previous)

            print("\n" + "=" * 60)
            print("Benchmark Comparison")
            print("=" * 60)
            print(f"Total comparisons: {comparison['total_comparisons']}")
            print(f"Regressions: {comparison['total_regressions']}")
            print(f"Improvements: {comparison['total_improvements']}")

            if comparison["regressions"]:
                print("\n⚠️  Regressions:")
                for reg in comparison["regressions"]:
                    print(f"  - {reg['name']}: +{reg['difference_pct']:.1f}% ({reg['difference_ms']:.3f}ms)")

            if comparison["improvements"]:
                print("\n✅ Improvements:")
                for imp in comparison["improvements"]:
                    print(f"  - {imp['name']}: {imp['difference_pct']:.1f}% ({imp['difference_ms']:.3f}ms)")

        except Exception as e:
            print(f"\n[ERROR] Failed to compare: {e}")

    # Print summary table
    print("\n" + "=" * 60)
    print("Benchmark Summary")
    print("=" * 60)
    print(f"{'Benchmark':<40} {'Mean (ms)':<12} {'P95 (ms)':<12} {'Throughput':<12}")
    print("-" * 76)

    for bench in summary["benchmarks"]:
        print(f"{bench['name']:<40} {bench['mean_ms']:<12.3f} {bench['p95_ms']:<12.3f} {bench['throughput_per_sec']:<12.2f}")

    print("\n✅ Benchmarks completed!")


if __name__ == "__main__":
    main()
