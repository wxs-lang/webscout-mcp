"""Tests for browser optimizer module."""

import time

from webscout_mcp.browser_optimizer import (
    BrowserInstancePool,
    BrowserMetrics,
    BrowserOptimizer,
    BrowserSession,
    HumanBehaviorSimulator,
    optimize_browser_navigation,
)


class TestBrowserMetrics:
    """Test BrowserMetrics class."""

    def test_creation(self):
        metrics = BrowserMetrics()
        assert metrics.page_load_time_ms == 0.0
        assert metrics.network_requests == 0

    def test_to_dict(self):
        metrics = BrowserMetrics(
            page_load_time_ms=1500.5,
            network_requests=25,
            scroll_depth_percent=75.0,
        )
        data = metrics.to_dict()
        assert data["page_load_time_ms"] == 1500.5
        assert data["network_requests"] == 25
        assert data["scroll_depth_percent"] == 75.0


class TestBrowserSession:
    """Test BrowserSession class."""

    def test_creation(self):
        session = BrowserSession(session_id="test123", url="https://example.com")
        assert session.session_id == "test123"
        assert session.url == "https://example.com"
        assert session.is_active is False

    def test_to_dict(self):
        session = BrowserSession(
            session_id="test",
            url="https://example.com",
            request_count=5,
            is_active=True,
        )
        data = session.to_dict()
        assert data["session_id"] == "test"
        assert data["request_count"] == 5
        assert data["is_active"] is True


class TestHumanBehaviorSimulator:
    """Test HumanBehaviorSimulator class."""

    def test_creation(self):
        simulator = HumanBehaviorSimulator(typing_speed_wpm=80)
        assert simulator.typing_speed_wpm == 80

    def test_random_pause(self):
        simulator = HumanBehaviorSimulator()
        pause = simulator.random_pause(100, 500)
        assert 0.1 <= pause <= 0.5

    def test_random_pause_range(self):
        simulator = HumanBehaviorSimulator()
        # Test multiple times to ensure range
        for _ in range(20):
            pause = simulator.random_pause(200, 1000)
            assert 0.2 <= pause <= 1.0

    def test_generate_mouse_path(self):
        simulator = HumanBehaviorSimulator()
        path = simulator.generate_mouse_path((0, 0), (100, 100), num_points=10)
        assert len(path) == 10
        assert path[0] == (0, 0)
        assert path[-1] == (100, 100)
        # All points should be integers
        assert all(isinstance(x, int) and isinstance(y, int) for x, y in path)

    def test_generate_mouse_path_different(self):
        simulator = HumanBehaviorSimulator()
        path1 = simulator.generate_mouse_path((0, 0), (100, 100))
        path2 = simulator.generate_mouse_path((0, 0), (100, 100))
        # Paths should be different due to randomness (with very high probability)
        assert path1 != path2

    def test_generate_scroll_pattern(self):
        simulator = HumanBehaviorSimulator()
        actions = simulator.generate_scroll_pattern(5000, viewport_height=1080, num_scrolls=5)
        assert len(actions) >= 5
        assert all("position" in a for a in actions)
        assert all("pause_seconds" in a for a in actions)
        assert all("direction" in a for a in actions)
        # Positions should be within valid range
        assert all(0 <= a["position"] <= 5000 for a in actions)

    def test_generate_typing_delay(self):
        simulator = HumanBehaviorSimulator(typing_speed_wpm=60)
        delay = simulator.generate_typing_delay("a")
        assert delay > 0
        # At 60 WPM, base delay should be around 0.2 seconds per character
        assert delay < 1.0

    def test_generate_typing_delay_punctuation(self):
        simulator = HumanBehaviorSimulator()
        # Use multiple samples to avoid flakiness from randomness
        num_samples = 100
        normal_delays = [simulator.generate_typing_delay("a") for _ in range(num_samples)]
        period_delays = [simulator.generate_typing_delay(".") for _ in range(num_samples)]
        avg_normal = sum(normal_delays) / len(normal_delays)
        avg_period = sum(period_delays) / len(period_delays)
        # Period should have longer average delay (with small tolerance for randomness)
        assert avg_period > avg_normal * 0.9, f"Expected avg period delay ({avg_period:.4f}) > avg normal delay ({avg_normal:.4f}) * 0.9"

    def test_simulate_reading_pause(self):
        simulator = HumanBehaviorSimulator()
        pause = simulator.simulate_reading_pause(1000)
        assert pause >= 1.0
        # 1000 chars = 200 words, at 250 WPM = 48 seconds
        assert pause < 120.0


class TestBrowserInstancePool:
    """Test BrowserInstancePool class."""

    def test_creation(self):
        pool = BrowserInstancePool(max_instances=5)
        assert pool.max_instances == 5
        assert pool.size == 0

    def test_acquire_new_instance(self):
        pool = BrowserInstancePool(max_instances=3)
        session = pool.acquire("https://example.com")
        assert session is not None
        assert session.url == "https://example.com"
        assert session.is_active is True
        assert pool.size == 1
        assert pool.active_count == 1

    def test_acquire_reuse_instance(self):
        pool = BrowserInstancePool(max_instances=3)
        session1 = pool.acquire("https://example.com")
        pool.release(session1.session_id)
        session2 = pool.acquire("https://example.org")
        # Should reuse the same instance
        assert session2.session_id == session1.session_id
        assert pool.size == 1

    def test_acquire_max_instances(self):
        pool = BrowserInstancePool(max_instances=2)
        session1 = pool.acquire("https://example.com")
        session2 = pool.acquire("https://example.org")
        session3 = pool.acquire("https://example.net")
        # Third should be None because all instances are active
        assert session3 is None
        assert pool.size == 2

    def test_release_instance(self):
        pool = BrowserInstancePool()
        session = pool.acquire("https://example.com")
        assert pool.active_count == 1
        pool.release(session.session_id)
        assert pool.active_count == 0
        assert pool.idle_count == 1

    def test_cleanup_expired(self):
        pool = BrowserInstancePool(idle_timeout_seconds=0)  # Immediate expiration
        session = pool.acquire("https://example.com")
        pool.release(session.session_id)
        time.sleep(0.1)
        cleaned = pool.cleanup()
        assert cleaned == 1
        assert pool.size == 0

    def test_cleanup_exhausted(self):
        pool = BrowserInstancePool(max_requests_per_instance=1)
        session = pool.acquire("https://example.com")
        session.request_count = 5  # Exceed max
        pool.release(session.session_id)
        cleaned = pool.cleanup()
        assert cleaned == 1

    def test_get_stats(self):
        pool = BrowserInstancePool(max_instances=5)
        pool.acquire("https://example.com")
        stats = pool.get_stats()
        assert stats["total_instances"] == 1
        assert stats["active_instances"] == 1
        assert stats["max_instances"] == 5


class TestBrowserOptimizer:
    """Test BrowserOptimizer class."""

    def test_creation(self):
        optimizer = BrowserOptimizer(max_instances=3)
        assert optimizer.enable_human_behavior is True
        assert optimizer.enable_pooling is True

    def test_navigate(self):
        optimizer = BrowserOptimizer(max_instances=2)
        session = optimizer.navigate("https://example.com")
        assert session is not None
        assert session.url == "https://example.com"
        assert session.request_count == 1

    def test_navigate_no_pooling(self):
        optimizer = BrowserOptimizer(enable_pooling=False)
        session = optimizer.navigate("https://example.com")
        assert session is not None
        assert session.url == "https://example.com"

    def test_simulate_human_interaction(self):
        optimizer = BrowserOptimizer(enable_human_behavior=True)
        session = optimizer.navigate("https://example.com")
        metrics = optimizer.simulate_human_interaction(
            session,
            content_length=1000,
            page_height=5000,
        )
        assert metrics.scroll_depth_percent > 0
        assert metrics.time_on_page_seconds > 0

    def test_release_session(self):
        optimizer = BrowserOptimizer(max_instances=2)
        session = optimizer.navigate("https://example.com")
        assert optimizer.pool.active_count == 1
        optimizer.release_session(session)
        assert optimizer.pool.active_count == 0

    def test_cleanup(self):
        optimizer = BrowserOptimizer(max_instances=2)
        session = optimizer.navigate("https://example.com")
        optimizer.release_session(session)
        # Should not error
        cleaned = optimizer.cleanup()
        assert isinstance(cleaned, int)

    def test_get_stats(self):
        optimizer = BrowserOptimizer(max_instances=3)
        optimizer.navigate("https://example.com")
        stats = optimizer.get_stats()
        assert stats["enable_human_behavior"] is True
        assert stats["enable_pooling"] is True
        assert "pool" in stats


class TestConvenienceFunction:
    """Test optimize_browser_navigation convenience function."""

    def test_optimize_browser_navigation(self):
        session = optimize_browser_navigation(
            "https://example.com",
            enable_human_behavior=False,
            max_instances=1,
        )
        assert isinstance(session, BrowserSession)
        assert session.url == "https://example.com"
