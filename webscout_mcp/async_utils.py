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
            "recent_timings": self._timings[-10:],
            "average_time_ms": (
                self._total_time_ms / len(self._timings) if self._timings else 0.0
            ),
            "max_history": self._max_history,
        }

    def reset(self) -> None:
        """Reset all collected metrics."""
        self._timings.clear()
        self._total_time_ms = 0.0


class _ConcurrencySlot:
    """Async context manager for a concurrency slot."""

    def __init__(self, limiter: "ConcurrencyLimiter") -> None:
        self._limiter = limiter

    async def __aenter__(self) -> "_ConcurrencySlot":
        await self._limiter._semaphore.acquire()
        self._limiter._total_operations += 1
        self._limiter._current_concurrent += 1
        if self._limiter._current_concurrent > self._limiter._peak_concurrent:
            self._limiter._peak_concurrent = self._limiter._current_concurrent
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._limiter._current_concurrent -= 1
        self._limiter._semaphore.release()


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

    def acquire(self) -> _ConcurrencySlot:
        """Acquire a concurrency slot.

        Usage:
            async with limiter.acquire():
                await do_work()

        Returns:
            Async context manager for the concurrency slot.
        """
        return _ConcurrencySlot(self)

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

        async def process_item(item: Any) -> T:
            async with self.acquire():
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
                self._total_wait_time / self._total_operations
                if self._total_operations > 0
                else 0.0
            ),
        }

    def reset(self) -> None:
        """Reset statistics."""
        self._current_concurrent = 0
        self._peak_concurrent = 0
        self._total_operations = 0
        self._total_wait_time = 0.0


__all__ = [
    "PerformanceMonitor",
    "ConcurrencyLimiter",
]
