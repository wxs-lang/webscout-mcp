"""Prometheus metrics module for webscout-mcp.

Collect and expose metrics for monitoring crawler performance, success rates,
and system health. Compatible with Prometheus scraping.

Features:
- Counter metrics (requests, errors, successes)
- Gauge metrics (active connections, cache size)
- Histogram metrics (response times, page sizes)
- Summary metrics (quantiles)
- Label support for multi-dimensional metrics
- Prometheus text format export
- In-memory metrics storage
- Metric registration and discovery
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .logging_config import get_logger

log = get_logger(__name__)


@dataclass
class Metric:
    """Base metric class."""

    name: str
    help: str = ""
    type: str = "gauge"
    labels: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "help": self.help,
            "type": self.type,
            "labels": self.labels,
        }


class Counter:
    """Counter metric - monotonically increasing value."""

    def __init__(self, name: str, help: str = "", labels: dict | None = None) -> None:
        self.name = name
        self.help = help
        self.labels = labels or {}
        self._value = 0.0
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0) -> None:
        """Increment counter by amount."""
        if amount < 0:
            raise ValueError("Counter can only be incremented")
        with self._lock:
            self._value += amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value

    def reset(self) -> None:
        with self._lock:
            self._value = 0.0


class Gauge:
    """Gauge metric - can go up and down."""

    def __init__(self, name: str, help: str = "", labels: dict | None = None) -> None:
        self.name = name
        self.help = help
        self.labels = labels or {}
        self._value = 0.0
        self._lock = threading.Lock()

    def set(self, value: float) -> None:
        """Set gauge to value."""
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        """Increment gauge by amount."""
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        """Decrement gauge by amount."""
        with self._lock:
            self._value -= amount

    @property
    def value(self) -> float:
        with self._lock:
            return self._value


class Histogram:
    """Histogram metric - tracks distribution of values."""

    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]

    def __init__(
        self,
        name: str,
        help: str = "",
        buckets: list[float] | None = None,
        labels: dict | None = None,
    ) -> None:
        self.name = name
        self.help = help
        self.buckets = sorted(buckets or self.DEFAULT_BUCKETS)
        self.labels = labels or {}
        self._count = 0
        self._sum = 0.0
        self._bucket_counts = [0] * len(self.buckets)
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """Observe a value."""
        with self._lock:
            self._count += 1
            self._sum += value
            for i, bucket in enumerate(self.buckets):
                if value <= bucket:
                    self._bucket_counts[i] += 1

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    @property
    def bucket_counts(self) -> list[int]:
        with self._lock:
            return list(self._bucket_counts)

    def reset(self) -> None:
        with self._lock:
            self._count = 0
            self._sum = 0.0
            self._bucket_counts = [0] * len(self.buckets)


class Summary:
    """Summary metric - tracks quantiles."""

    def __init__(self, name: str, help: str = "", labels: dict | None = None) -> None:
        self.name = name
        self.help = help
        self.labels = labels or {}
        self._count = 0
        self._sum = 0.0
        self._values: list[float] = []
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """Observe a value."""
        with self._lock:
            self._count += 1
            self._sum += value
            self._values.append(value)
            # Keep only last 1000 values for memory efficiency
            if len(self._values) > 1000:
                self._values = self._values[-1000:]

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    def quantile(self, q: float) -> float:
        """Calculate quantile."""
        with self._lock:
            if not self._values:
                return 0.0
            sorted_values = sorted(self._values)
            index = int(q * (len(sorted_values) - 1))
            return sorted_values[index]

    def reset(self) -> None:
        with self._lock:
            self._count = 0
            self._sum = 0.0
            self._values = []


class MetricsRegistry:
    """Registry for all metrics."""

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._summaries: dict[str, Summary] = {}
        self._lock = threading.Lock()

    def register_counter(self, name: str, help: str = "", labels: dict | None = None) -> Counter:
        """Register a counter metric."""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name, help, labels)
            return self._counters[name]

    def register_gauge(self, name: str, help: str = "", labels: dict | None = None) -> Gauge:
        """Register a gauge metric."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name, help, labels)
            return self._gauges[name]

    def register_histogram(
        self,
        name: str,
        help: str = "",
        buckets: list[float] | None = None,
        labels: dict | None = None,
    ) -> Histogram:
        """Register a histogram metric."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, help, buckets, labels)
            return self._histograms[name]

    def register_summary(self, name: str, help: str = "", labels: dict | None = None) -> Summary:
        """Register a summary metric."""
        with self._lock:
            if name not in self._summaries:
                self._summaries[name] = Summary(name, help, labels)
            return self._summaries[name]

    def get_counter(self, name: str) -> Counter | None:
        return self._counters.get(name)

    def get_gauge(self, name: str) -> Gauge | None:
        return self._gauges.get(name)

    def get_histogram(self, name: str) -> Histogram | None:
        return self._histograms.get(name)

    def get_summary(self, name: str) -> Summary | None:
        return self._summaries.get(name)

    def generate_prometheus_format(self) -> str:
        """Generate metrics in Prometheus text format."""
        lines = []

        # Counters
        for name, counter in self._counters.items():
            if counter.help:
                lines.append(f"# HELP {name} {counter.help}")
            lines.append(f"# TYPE {name} counter")
            label_str = self._format_labels(counter.labels)
            lines.append(f"{name}{label_str} {counter.value}")

        # Gauges
        for name, gauge in self._gauges.items():
            if gauge.help:
                lines.append(f"# HELP {name} {gauge.help}")
            lines.append(f"# TYPE {name} gauge")
            label_str = self._format_labels(gauge.labels)
            lines.append(f"{name}{label_str} {gauge.value}")

        # Histograms
        for name, histogram in self._histograms.items():
            if histogram.help:
                lines.append(f"# HELP {name} {histogram.help}")
            lines.append(f"# TYPE {name} histogram")
            label_str = self._format_labels(histogram.labels)
            for i, bucket in enumerate(histogram.buckets):
                count = histogram.bucket_counts[i] if i < len(histogram.bucket_counts) else 0
                if label_str:
                    # label_str is like {key="value"}, remove last } and add le label
                    bucket_label = label_str[:-1] + f',le="{bucket}"}}'
                else:
                    bucket_label = f'{{le="{bucket}"}}'
                lines.append(f"{name}_bucket{bucket_label} {count}")
            lines.append(f"{name}_count{label_str} {histogram.count}")
            lines.append(f"{name}_sum{label_str} {histogram.sum}")

        # Summaries
        for name, summary in self._summaries.items():
            if summary.help:
                lines.append(f"# HELP {name} {summary.help}")
            lines.append(f"# TYPE {name} summary")
            label_str = self._format_labels(summary.labels)
            for q in [0.5, 0.9, 0.99]:
                quantile_val = summary.quantile(q)
                if label_str:
                    quantile_label = label_str[:-1] + f',quantile="{q}"}}'
                else:
                    quantile_label = f'{{quantile="{q}"}}'
                lines.append(f"{name}{quantile_label} {quantile_val}")
            lines.append(f"{name}_count{label_str} {summary.count}")
            lines.append(f"{name}_sum{label_str} {summary.sum}")

        return "\n".join(lines) + "\n"

    def _format_labels(self, labels: dict) -> str:
        """Format labels for Prometheus."""
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in labels.items()]
        return "{" + ",".join(parts) + "}"

    def get_stats(self) -> dict:
        """Get registry statistics."""
        return {
            "num_counters": len(self._counters),
            "num_gauges": len(self._gauges),
            "num_histograms": len(self._histograms),
            "num_summaries": len(self._summaries),
            "total_metrics": (len(self._counters) + len(self._gauges) + len(self._histograms) + len(self._summaries)),
        }


# Global default registry
_default_registry = MetricsRegistry()


def get_default_registry() -> MetricsRegistry:
    """Get the default global metrics registry."""
    return _default_registry


class WebScoutMetrics:
    """Pre-defined metrics for webscout-mcp."""

    def __init__(self, registry: MetricsRegistry | None = None) -> None:
        self.registry = registry or get_default_registry()
        self._init_metrics()

    def _init_metrics(self) -> None:
        """Initialize all webscout metrics."""
        # Search metrics
        self.search_requests = self.registry.register_counter(
            "webscout_search_requests_total",
            "Total number of search requests",
        )
        self.search_errors = self.registry.register_counter(
            "webscout_search_errors_total",
            "Total number of search errors",
        )
        self.search_duration = self.registry.register_histogram(
            "webscout_search_duration_seconds",
            "Search request duration in seconds",
        )

        # Fetch metrics
        self.fetch_requests = self.registry.register_counter(
            "webscout_fetch_requests_total",
            "Total number of fetch requests",
        )
        self.fetch_errors = self.registry.register_counter(
            "webscout_fetch_errors_total",
            "Total number of fetch errors",
        )
        self.fetch_duration = self.registry.register_histogram(
            "webscout_fetch_duration_seconds",
            "Fetch request duration in seconds",
        )

        # Crawl metrics
        self.crawl_pages_total = self.registry.register_counter(
            "webscout_crawl_pages_total",
            "Total number of crawled pages",
        )
        self.crawl_errors = self.registry.register_counter(
            "webscout_crawl_errors_total",
            "Total number of crawl errors",
        )
        self.crawl_active = self.registry.register_gauge(
            "webscout_crawl_active",
            "Number of active crawl jobs",
        )

        # Cache metrics
        self.cache_hits = self.registry.register_counter(
            "webscout_cache_hits_total",
            "Total number of cache hits",
        )
        self.cache_misses = self.registry.register_counter(
            "webscout_cache_misses_total",
            "Total number of cache misses",
        )
        self.cache_size = self.registry.register_gauge(
            "webscout_cache_size",
            "Current cache size",
        )

        # System metrics
        self.active_connections = self.registry.register_gauge(
            "webscout_active_connections",
            "Number of active connections",
        )
        self.requests_in_progress = self.registry.register_gauge(
            "webscout_requests_in_progress",
            "Number of requests in progress",
        )

    def observe_search(self, duration: float, success: bool = True) -> None:
        """Observe a search request."""
        self.search_requests.inc()
        self.search_duration.observe(duration)
        if not success:
            self.search_errors.inc()

    def observe_fetch(self, duration: float, success: bool = True) -> None:
        """Observe a fetch request."""
        self.fetch_requests.inc()
        self.fetch_duration.observe(duration)
        if not success:
            self.fetch_errors.inc()

    def observe_cache(self, hit: bool) -> None:
        """Observe a cache access."""
        if hit:
            self.cache_hits.inc()
        else:
            self.cache_misses.inc()

    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate."""
        hits = self.cache_hits.value
        misses = self.cache_misses.value
        total = hits + misses
        return round(hits / total, 3) if total > 0 else 0.0

    def generate_metrics(self) -> str:
        """Generate Prometheus format metrics."""
        return self.registry.generate_prometheus_format()


# Global metrics instance
_metrics = None


def get_metrics() -> WebScoutMetrics:
    """Get the global WebScout metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = WebScoutMetrics()
    return _metrics
