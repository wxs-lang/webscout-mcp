"""Async utilities and performance optimization module for webscout-mcp.

Provides async helpers, concurrency control, retry logic, performance monitoring,
and request tracing.

Features:
- Async retry with exponential backoff
- Concurrency limiting (semaphore)
- Async task batch processing
- Performance timing and profiling
- Request ID generation and propagation
- Memory usage monitoring
- Connection pool management
- Circuit breaker pattern
"""
from __future__ import annotations
import asyncio
import time
import uuid
import random
import functools
import tracemalloc
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple, Callable, TypeVar, Awaitable
from contextlib import contextmanager, asynccontextmanager
from .logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")


# ============ Request ID ============

class RequestID:
    """Generate and manage request IDs for tracing."""

    @staticmethod
    def generate() -> str:
        """Generate a unique request ID."""
        return str(uuid.uuid4())[:8]

    @staticmethod
    def generate_short() -> str:
        """Generate a short request ID."""
        return uuid.uuid4().hex[:8]


# ============ Performance Timing ============

@dataclass
class TimingResult:
    """Result of a timing measurement."""
    name: str = ""
    duration_ms: float = 0.0
    start_time: float = 0.0
    end_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "duration_ms": self.duration_ms,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "metadata": self.metadata,
        }


class PerformanceMonitor:
    """Monitor and record performance metrics."""

    def __init__(self) -> None:
        self._timings: List[TimingResult] = []
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}

    @contextmanager
    def time(self, name: str, metadata: Optional[Dict[str, Any]] = None):
        """Context manager to time a block of code.

        Usage:
            with monitor.time("operation"):
                do_something()
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            end = time.perf_counter()
            result = TimingResult(
                name=name,
                duration_ms=(end - start) * 1000,
                start_time=start,
                end_time=end,
                metadata=metadata or {},
            )
            self._timings.append(result)
            log.debug(f"Timing: {name} = {result.duration_ms:.2f}ms")

    def time_function(self, func: Callable) -> Callable:
        """Decorator to time a function.

        Usage:
            @monitor.time_function
            def my_function():
                pass
        """
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self.time(func.__name__):
                return func(*args, **kwargs)
        return wrapper

    def time_async_function(self, func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """Decorator to time an async function."""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                return await func(*args, **kwargs)
            finally:
                end = time.perf_counter()
                result = TimingResult(
                    name=func.__name__,
                    duration_ms=(end - start) * 1000,
                    start_time=start,
                    end_time=end,
                )
                self._timings.append(result)
        return wrapper

    def increment_counter(self, name: str, amount: int = 1) -> None:
        """Increment a counter."""
        self._counters[name] = self._counters.get(name, 0) + amount

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge value."""
        self._gauges[name] = value

    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        base_stats = {
            "total_timings": len(self._timings),
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
        }

        if not self._timings:
            return base_stats

        durations = [t.duration_ms for t in self._timings]
        base_stats.update({
            "total_time_ms": sum(durations),
            "avg_time_ms": sum(durations) / len(durations),
            "min_time_ms": min(durations),
            "max_time_ms": max(durations),
            "recent_timings": [t.to_dict() for t in self._timings[-10:]],
        })
        return base_stats

    def reset(self) -> None:
        """Reset all metrics."""
        self._timings.clear()
        self._counters.clear()
        self._gauges.clear()


# Global performance monitor instance
performance_monitor = PerformanceMonitor()


# ============ Async Retry ============

class AsyncRetry:
    """Async retry with exponential backoff.

    Retries an async operation on failure with increasing delays.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        retry_exceptions: Tuple[type, ...] = (Exception,),
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self.retry_exceptions = retry_exceptions

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a retry attempt."""
        delay = min(self.max_delay, self.base_delay * (self.backoff_factor ** attempt))
        if self.jitter:
            delay *= 0.5 + random.random() * 0.5
        return delay

    async def execute(self, func: Callable[..., Awaitable[T]], *args, **kwargs) -> T:
        """Execute an async function with retry.

        Args:
            func: Async function to execute.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Function result.

        Raises:
            Last exception if all retries fail.
        """
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except self.retry_exceptions as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = self.calculate_delay(attempt)
                    log.warning(f"Retry {attempt + 1}/{self.max_retries} for {func.__name__}: {exc}. Waiting {delay:.2f}s")
                    await asyncio.sleep(delay)
                else:
                    log.error(f"All retries failed for {func.__name__}: {exc}")

        raise last_exception  # type: ignore

    def decorate(self, func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        """Decorator for async retry."""
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.execute(func, *args, **kwargs)
        return wrapper


# ============ Concurrency Limiter ============

class ConcurrencyLimiter:
    """Limit concurrent async operations using a semaphore.

    Usage:
        limiter = ConcurrencyLimiter(max_concurrent=10)
        async with limiter:
            await do_something()
    """

    def __init__(self, max_concurrent: int = 10) -> None:
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active = 0
        self._completed = 0
        self._failed = 0

    @asynccontextmanager
    async def acquire(self):
        """Acquire a slot for concurrent execution."""
        async with self._semaphore:
            self._active += 1
            try:
                yield
                self._completed += 1
            except Exception:
                self._failed += 1
                raise
            finally:
                self._active -= 1

    async def map(self, func: Callable[..., Awaitable[T]], items: List[Any], *args, **kwargs) -> List[T]:
        """Map an async function over items with concurrency limit.

        Args:
            func: Async function to apply.
            items: Items to process.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            List of results in order.
        """
        async def process_item(item):
            async with self.acquire():
                return await func(item, *args, **kwargs)

        tasks = [process_item(item) for item in items]
        return await asyncio.gather(*tasks)

    def get_stats(self) -> Dict[str, Any]:
        """Get concurrency statistics."""
        return {
            "max_concurrent": self.max_concurrent,
            "active": self._active,
            "completed": self._completed,
            "failed": self._failed,
            "available": self.max_concurrent - self._active,
        }


# ============ Circuit Breaker ============

class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance.

    Prevents cascading failures by stopping requests to a failing service.
    States: CLOSED -> OPEN -> HALF_OPEN -> CLOSED
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.half_open_calls = 0

    def call(self, func: Callable, *args, **kwargs):
        """Execute a function with circuit breaker protection.

        Args:
            func: Function to execute.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Function result.

        Raises:
            Exception: If circuit is open or function fails.
        """
        if self.state == self.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = self.HALF_OPEN
                self.half_open_calls = 0
                log.info("Circuit breaker transitioning to HALF_OPEN")
            else:
                raise Exception(f"Circuit breaker is OPEN. Try again in {self.recovery_timeout - (time.time() - self.last_failure_time):.1f}s")

        if self.state == self.HALF_OPEN and self.half_open_calls >= self.half_open_max_calls:
            raise Exception("Circuit breaker is in HALF_OPEN with max calls")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise exc

    def _on_success(self) -> None:
        """Handle successful call."""
        if self.state == self.HALF_OPEN:
            self.half_open_calls += 1
            if self.half_open_calls >= self.half_open_max_calls:
                self.state = self.CLOSED
                self.failure_count = 0
                log.info("Circuit breaker recovering to CLOSED")
        else:
            self.failure_count = max(0, self.failure_count - 1)

    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == self.HALF_OPEN:
            self.state = self.OPEN
            log.warning("Circuit breaker failing back to OPEN")
        elif self.failure_count >= self.failure_threshold:
            self.state = self.OPEN
            log.warning(f"Circuit breaker opening after {self.failure_count} failures")

    def get_state(self) -> str:
        """Get current circuit breaker state."""
        return self.state

    def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self.state = self.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.half_open_calls = 0


# ============ Memory Monitor ============

class MemoryMonitor:
    """Monitor memory usage."""

    def __init__(self) -> None:
        self._snapshots: List[Dict[str, Any]] = []

    @contextmanager
    def track(self, name: str = ""):
        """Context manager to track memory usage of a block."""
        tracemalloc.start()
        start_snapshot = tracemalloc.take_snapshot()
        try:
            yield
        finally:
            end_snapshot = tracemalloc.take_snapshot()
            stats = end_snapshot.compare_to(start_snapshot, "lineno")
            total_diff = sum(stat.size_diff for stat in stats)
            self._snapshots.append({
                "name": name,
                "memory_diff_bytes": total_diff,
                "top_allocations": [(str(stat.traceback), stat.size_diff) for stat in stats[:5]],
            })
            tracemalloc.stop()

    def get_current_usage(self) -> Dict[str, Any]:
        """Get current memory usage."""
        import resource
        usage = resource.getrusage(resource.RUSAGE_SELF)
        return {
            "max_rss_mb": usage.ru_maxrss / 1024,  # Convert KB to MB
            "shared_memory_mb": usage.ru_ixrss / 1024,
            "data_memory_mb": usage.ru_idrss / 1024,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get memory monitoring statistics."""
        return {
            "snapshots": self._snapshots,
            "current_usage": self.get_current_usage(),
        }


# ============ Batch Processor ============

class BatchProcessor:
    """Process items in batches with configurable batch size and concurrency."""

    def __init__(
        self,
        batch_size: int = 10,
        max_concurrent: int = 5,
        delay_between_batches: float = 0.0,
    ) -> None:
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent
        self.delay_between_batches = delay_between_batches

    def chunk(self, items: List[Any]) -> List[List[Any]]:
        """Split items into batches."""
        return [items[i:i + self.batch_size] for i in range(0, len(items), self.batch_size)]

    async def process(
        self,
        items: List[Any],
        processor: Callable[[Any], Awaitable[T]],
    ) -> List[T]:
        """Process items in batches.

        Args:
            items: Items to process.
            processor: Async processor function.

        Returns:
            List of results.
        """
        batches = self.chunk(items)
        all_results = []

        for batch_idx, batch in enumerate(batches):
            limiter = ConcurrencyLimiter(max_concurrent=self.max_concurrent)
            batch_results = await limiter.map(processor, batch)
            all_results.extend(batch_results)

            if batch_idx < len(batches) - 1 and self.delay_between_batches > 0:
                await asyncio.sleep(self.delay_between_batches)

        return all_results


# ============ Convenience Functions ============

def timeit(func: Callable) -> Callable:
    """Decorator to time a function using global performance monitor."""
    return performance_monitor.time_function(func)


def async_timeit(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """Decorator to time an async function."""
    return performance_monitor.time_async_function(func)


def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs,
) -> Callable:
    """Decorator for async retry."""
    retry = AsyncRetry(max_retries=max_retries, base_delay=base_delay, **kwargs)
    return retry.decorate


def generate_request_id() -> str:
    """Generate a request ID."""
    return RequestID.generate()
