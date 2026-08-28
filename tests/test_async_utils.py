"""Tests for async utilities and performance optimization module."""
import pytest
import asyncio
import time
from webscout_mcp.async_utils import (
    RequestID,
    TimingResult,
    PerformanceMonitor,
    performance_monitor,
    AsyncRetry,
    ConcurrencyLimiter,
    CircuitBreaker,
    MemoryMonitor,
    BatchProcessor,
    timeit,
    async_timeit,
    with_retry,
    generate_request_id,
)


# ============ Request ID Tests ============

class TestRequestID:
    """Test RequestID class."""

    def test_generate(self):
        rid = RequestID.generate()
        assert len(rid) == 8
        assert isinstance(rid, str)

    def test_generate_unique(self):
        ids = {RequestID.generate() for _ in range(100)}
        assert len(ids) == 100  # All unique

    def test_generate_short(self):
        rid = RequestID.generate_short()
        assert len(rid) == 8
        assert isinstance(rid, str)


# ============ Performance Monitor Tests ============

class TestPerformanceMonitor:
    """Test PerformanceMonitor class."""

    def test_creation(self):
        monitor = PerformanceMonitor()
        assert monitor is not None

    def test_time_context_manager(self):
        monitor = PerformanceMonitor()
        with monitor.time("test_operation"):
            time.sleep(0.01)
        stats = monitor.get_stats()
        assert stats["total_timings"] == 1
        assert stats["avg_time_ms"] > 0

    def test_time_function_decorator(self):
        monitor = PerformanceMonitor()

        @monitor.time_function
        def slow_function():
            time.sleep(0.01)
            return "done"

        result = slow_function()
        assert result == "done"
        stats = monitor.get_stats()
        assert stats["total_timings"] == 1

    def test_time_async_function_decorator(self):
        monitor = PerformanceMonitor()

        @monitor.time_async_function
        async def slow_async():
            await asyncio.sleep(0.01)
            return "done"

        result = asyncio.run(slow_async())
        assert result == "done"
        stats = monitor.get_stats()
        assert stats["total_timings"] == 1

    def test_increment_counter(self):
        monitor = PerformanceMonitor()
        monitor.increment_counter("requests")
        monitor.increment_counter("requests", 5)
        stats = monitor.get_stats()
        assert stats["counters"]["requests"] == 6

    def test_set_gauge(self):
        monitor = PerformanceMonitor()
        monitor.set_gauge("memory_usage", 100.5)
        stats = monitor.get_stats()
        assert stats["gauges"]["memory_usage"] == 100.5

    def test_reset(self):
        monitor = PerformanceMonitor()
        with monitor.time("test"):
            pass
        monitor.increment_counter("test")
        monitor.reset()
        stats = monitor.get_stats()
        assert stats["total_timings"] == 0

    def test_global_monitor(self):
        assert performance_monitor is not None
        assert isinstance(performance_monitor, PerformanceMonitor)


# ============ Async Retry Tests ============

class TestAsyncRetry:
    """Test AsyncRetry class."""

    def test_creation(self):
        retry = AsyncRetry(max_retries=3, base_delay=0.1)
        assert retry.max_retries == 3
        assert retry.base_delay == 0.1

    def test_calculate_delay(self):
        retry = AsyncRetry(base_delay=1.0, backoff_factor=2.0, jitter=False)
        assert retry.calculate_delay(0) == 1.0
        assert retry.calculate_delay(1) == 2.0
        assert retry.calculate_delay(2) == 4.0

    def test_calculate_delay_max(self):
        retry = AsyncRetry(base_delay=1.0, max_delay=5.0, backoff_factor=2.0, jitter=False)
        assert retry.calculate_delay(10) == 5.0  # Capped at max_delay

    def test_execute_success(self):
        retry = AsyncRetry(max_retries=3, base_delay=0.01)

        async def success_func():
            return "success"

        result = asyncio.run(retry.execute(success_func))
        assert result == "success"

    def test_execute_retry_then_success(self):
        retry = AsyncRetry(max_retries=3, base_delay=0.01)
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("temporary error")
            return "success"

        result = asyncio.run(retry.execute(flaky_func))
        assert result == "success"
        assert call_count == 3

    def test_execute_all_fail(self):
        retry = AsyncRetry(max_retries=2, base_delay=0.01)

        async def always_fail():
            raise ValueError("permanent error")

        with pytest.raises(ValueError):
            asyncio.run(retry.execute(always_fail))

    def test_decorate(self):
        retry = AsyncRetry(max_retries=2, base_delay=0.01)

        @retry.decorate
        async def test_func():
            return "decorated"

        result = asyncio.run(test_func())
        assert result == "decorated"


# ============ Concurrency Limiter Tests ============

class TestConcurrencyLimiter:
    """Test ConcurrencyLimiter class."""

    def test_creation(self):
        limiter = ConcurrencyLimiter(max_concurrent=5)
        assert limiter.max_concurrent == 5

    def test_acquire(self):
        limiter = ConcurrencyLimiter(max_concurrent=2)

        async def test():
            async with limiter.acquire():
                assert limiter._active == 1

        asyncio.run(test())

    def test_map(self):
        limiter = ConcurrencyLimiter(max_concurrent=3)

        async def processor(item):
            await asyncio.sleep(0.01)
            return item * 2

        results = asyncio.run(limiter.map(processor, [1, 2, 3, 4, 5]))
        assert results == [2, 4, 6, 8, 10]

    def test_get_stats(self):
        limiter = ConcurrencyLimiter(max_concurrent=5)
        stats = limiter.get_stats()
        assert stats["max_concurrent"] == 5
        assert stats["active"] == 0
        assert stats["available"] == 5


# ============ Circuit Breaker Tests ============

class TestCircuitBreaker:
    """Test CircuitBreaker class."""

    def test_creation(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        assert cb.failure_threshold == 3
        assert cb.state == CircuitBreaker.CLOSED

    def test_call_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        result = cb.call(lambda: "success")
        assert result == "success"
        assert cb.state == CircuitBreaker.CLOSED

    def test_call_failure_opens_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)

        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("error")))
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("error")))

        assert cb.state == CircuitBreaker.OPEN

        # Next call should fail immediately without executing
        with pytest.raises(Exception, match="Circuit breaker is OPEN"):
            cb.call(lambda: "should not execute")

    def test_half_open_recovery(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1, half_open_max_calls=2)

        # Fail to open circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("error")))

        assert cb.state == CircuitBreaker.OPEN

        # Wait for recovery timeout
        time.sleep(0.15)

        # Successful calls should close circuit
        cb.call(lambda: "success1")
        cb.call(lambda: "success2")

        assert cb.state == CircuitBreaker.CLOSED

    def test_get_state(self):
        cb = CircuitBreaker()
        assert cb.get_state() == "closed"

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("error")))
        assert cb.state == CircuitBreaker.OPEN
        cb.reset()
        assert cb.state == CircuitBreaker.CLOSED


# ============ Memory Monitor Tests ============

class TestMemoryMonitor:
    """Test MemoryMonitor class."""

    def test_creation(self):
        monitor = MemoryMonitor()
        assert monitor is not None

    def test_track(self):
        monitor = MemoryMonitor()
        with monitor.track("test_allocation"):
            _ = [i * 2 for i in range(1000)]
        stats = monitor.get_stats()
        assert len(stats["snapshots"]) == 1

    def test_get_current_usage(self):
        monitor = MemoryMonitor()
        usage = monitor.get_current_usage()
        assert "max_rss_mb" in usage
        assert usage["max_rss_mb"] > 0


# ============ Batch Processor Tests ============

class TestBatchProcessor:
    """Test BatchProcessor class."""

    def test_creation(self):
        processor = BatchProcessor(batch_size=5, max_concurrent=2)
        assert processor.batch_size == 5
        assert processor.max_concurrent == 2

    def test_chunk(self):
        processor = BatchProcessor(batch_size=3)
        batches = processor.chunk([1, 2, 3, 4, 5, 6, 7])
        assert len(batches) == 3
        assert batches[0] == [1, 2, 3]
        assert batches[1] == [4, 5, 6]
        assert batches[2] == [7]

    def test_process(self):
        processor = BatchProcessor(batch_size=2, max_concurrent=2)

        async def processor_func(item):
            await asyncio.sleep(0.01)
            return item * 2

        results = asyncio.run(processor.process([1, 2, 3, 4], processor_func))
        assert results == [2, 4, 6, 8]


# ============ Convenience Function Tests ============

class TestConvenienceFunctions:
    """Test convenience functions and decorators."""

    def test_timeit_decorator(self):
        @timeit
        def test_func():
            return "timed"

        result = test_func()
        assert result == "timed"

    def test_async_timeit_decorator(self):
        @async_timeit
        async def test_func():
            return "async_timed"

        result = asyncio.run(test_func())
        assert result == "async_timed"

    def test_with_retry_decorator(self):
        @with_retry(max_retries=2, base_delay=0.01)
        async def test_func():
            return "retried"

        result = asyncio.run(test_func())
        assert result == "retried"

    def test_generate_request_id(self):
        rid = generate_request_id()
        assert len(rid) == 8
        assert isinstance(rid, str)
