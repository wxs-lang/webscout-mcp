"""
Async utilities for webscout-mcp.

Provides performance monitoring, concurrency limiting, and other async helpers.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from typing import Any, TypeVar

T = TypeVar("T")


class PerformanceMonitor:
    """Monitor and track performance metrics for operations.

    Provides timing context managers and statistics collection.
    """

    def __init__(self, max_history: int = 1000) -> None:
        """Initialize performance monitor.

        Args:
            max_history: Maximum number of timing records to keep.
        """
        self._timings: list[dict[str, Any]] = []
        self._max_history = max_history
        self._total_time_ms: float = 0.0

    @contextmanager
    def time(self, name: str):
        """Time a block of code.

        Args:
            name: Name of the operation being timed.

        Yields:
            None
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self._record_timing(name, elapsed_ms)

    def _record_timing(self, name: str, elapsed_ms: float) -> None:
        """Record a timing measurement.

        Args:
            name: Name of the operation.
            elapsed_ms: Elapsed time in milliseconds.
        """
        self._timings.append(
            {
                "name": name,
                "elapsed_ms": elapsed_ms,
                "timestamp": time.time(),
            }
        )
        self._total_time_ms += elapsed_ms

        # Trim history if needed
        if len(self._timings) > self._max_history:
            self._timings = self._timings[-self._max_history :]

    def get_stats(self) -> dict[str, Any]:
        """Get performance statistics.

        Returns:
            Dictionary with performance statistics.
        """
        return {
            "total_timings": len(self._timings),
            "total_time_ms": self._total_time_ms,
            "recent_timings": self._timings[-10:],  # Last 10 timings
            "average_time_ms": (self._total_time_ms / len(self._timings) if self._timings else 0.0),
            "max_history": self._max_history,
        }

    def get_timing_by_name(self, name: str) -> list[dict[str, Any]]:
        """Get all timings for a specific operation name.

        Args:
            name: Name of the operation.

        Returns:
            List of timing records.
        """
        return [t for t in self._timings if t["name"] == name]

    def reset(self) -> None:
        """Reset all collected metrics."""
        self._timings.clear()
        self._total_time_ms = 0.0


class ConcurrencyLimiter:
    """Limit the number of concurrent async operations.

    Provides a semaphore-based limiter with statistics tracking.
    """

    def __init__(self, max_concurrent: int = 10) -> None:
        """Initialize concurrency limiter.

        Args:
            max_concurrent: Maximum number of concurrent operations.
        """
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._current_concurrent = 0
        self._peak_concurrent = 0
        self._total_operations = 0
        self._total_wait_time = 0.0

    @contextmanager
    def _track_concurrency(self):
        """Track current concurrency level."""
        self._current_concurrent += 1
        self._peak_concurrent = max(self._peak_concurrent, self._current_concurrent)
        try:
            yield
        finally:
            self._current_concurrent -= 1

    @contextmanager
    async def acquire(self):
        """Acquire a concurrency slot.

        Usage:
            async with limiter.acquire():
                await do_work()

        Yields:
            None
        """
        wait_start = time.perf_counter()
        async with self._semaphore:
            wait_time = (time.perf_counter() - wait_start) * 1000
            self._total_wait_time += wait_time
            self._total_operations += 1
            with self._track_concurrency():
                yield

    async def map(
        self,
        func: Callable[[Any], Awaitable[T]],
        items: list[Any],
    ) -> list[T]:
        """Apply an async function to items with concurrency limiting.

        Args:
            func: Async function to apply.
            items: List of items to process.

        Returns:
            List of results in the same order as input items.
        """
        semaphore = self._semaphore

        async def process_item(item: Any) -> T:
            async with semaphore:
                self._total_operations += 1
                with self._track_concurrency():
                    return await func(item)

        tasks = [process_item(item) for item in items]
        results = await asyncio.gather(*tasks)
        return list(results)

    def get_stats(self) -> dict[str, Any]:
        """Get concurrency limiter statistics.

        Returns:
            Dictionary with statistics.
        """
        return {
            "max_concurrent": self._max_concurrent,
            "current_concurrent": self._current_concurrent,
            "peak_concurrent": self._peak_concurrent,
            "total_operations": self._total_operations,
            "total_wait_time_ms": self._total_wait_time,
            "average_wait_time_ms": (
                self._total_wait_time / self._total_operations if self._total_operations > 0 else 0.0
            ),
        }

    def reset(self) -> None:
        """Reset statistics."""
        self._current_concurrent = 0
        self._peak_concurrent = 0
        self._total_operations = 0
        self._total_wait_time = 0.0


class AsyncRateLimiter:
    """Async rate limiter using token bucket algorithm.

    Limits the number of operations per time period.
    """

    def __init__(self, rate: float = 10.0, burst: int = 5) -> None:
        """Initialize async rate limiter.

        Args:
            rate: Tokens per second.
            burst: Maximum burst size.
        """
        self._rate = rate
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire.
        """
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait_time = (tokens - self._tokens) / self._rate
                await asyncio.sleep(wait_time)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens without waiting.

        Args:
            tokens: Number of tokens to acquire.

        Returns:
            True if tokens were acquired, False otherwise.
        """
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiter statistics.

        Returns:
            Dictionary with statistics.
        """
        return {
            "rate": self._rate,
            "burst": self._burst,
            "current_tokens": self._tokens,
        }


class AsyncRetrier:
    """Async retry helper with exponential backoff.

    Retries failed operations with configurable backoff strategy.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        retry_exceptions: tuple = (Exception,),
    ) -> None:
        """Initialize async retrier.

        Args:
            max_retries: Maximum number of retries.
            base_delay: Initial delay in seconds.
            max_delay: Maximum delay in seconds.
            backoff_factor: Multiplier for exponential backoff.
            retry_exceptions: Exception types to retry on.
        """
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._backoff_factor = backoff_factor
        self._retry_exceptions = retry_exceptions
        self._total_retries = 0
        self._total_failures = 0

    async def execute(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute an async function with retries.

        Args:
            func: Async function to execute.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Result of the function.

        Raises:
            Last exception if all retries fail.
        """
        last_exception: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except self._retry_exceptions as e:
                last_exception = e
                self._total_retries += 1

                if attempt < self._max_retries:
                    delay = min(
                        self._base_delay * (self._backoff_factor**attempt),
                        self._max_delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    self._total_failures += 1

        assert last_exception is not None
        raise last_exception

    def get_stats(self) -> dict[str, Any]:
        """Get retrier statistics.

        Returns:
            Dictionary with statistics.
        """
        return {
            "max_retries": self._max_retries,
            "base_delay": self._base_delay,
            "max_delay": self._max_delay,
            "backoff_factor": self._backoff_factor,
            "total_retries": self._total_retries,
            "total_failures": self._total_failures,
        }


__all__ = [
    "AsyncRateLimiter",
    "AsyncRetrier",
    "ConcurrencyLimiter",
    "PerformanceMonitor",
]
