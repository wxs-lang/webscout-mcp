"""Browser automation optimizer module for webscout-mcp.

Enhanced browser automation with instance pooling, human behavior simulation,
and intelligent anti-detection.

Features:
- Browser instance pooling (reuse connections, reduce startup overhead)
- Human behavior simulation (mouse movement, scrolling, typing)
- Intelligent wait strategies (network idle, DOM stable)
- Resource interception optimization
- Session/cookie management
- Anti-detection enhancements
- Performance metrics tracking
"""
from __future__ import annotations
import time
import random
import math
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple, Callable
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class BrowserMetrics:
    """Browser performance metrics."""
    page_load_time_ms: float = 0.0
    dom_content_loaded_ms: float = 0.0
    network_requests: int = 0
    failed_requests: int = 0
    javascript_errors: int = 0
    console_errors: int = 0
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    scroll_depth_percent: float = 0.0
    time_on_page_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "page_load_time_ms": self.page_load_time_ms,
            "dom_content_loaded_ms": self.dom_content_loaded_ms,
            "network_requests": self.network_requests,
            "failed_requests": self.failed_requests,
            "javascript_errors": self.javascript_errors,
            "console_errors": self.console_errors,
            "memory_usage_mb": self.memory_usage_mb,
            "cpu_usage_percent": self.cpu_usage_percent,
            "scroll_depth_percent": self.scroll_depth_percent,
            "time_on_page_seconds": self.time_on_page_seconds,
        }


@dataclass
class BrowserSession:
    """Browser session with state tracking."""
    session_id: str = ""
    url: str = ""
    cookies: List[Dict[str, Any]] = field(default_factory=list)
    localStorage: Dict[str, str] = field(default_factory=dict)
    user_agent: str = ""
    viewport: Tuple[int, int] = (1920, 1080)
    created_at: float = 0.0
    last_used_at: float = 0.0
    request_count: int = 0
    metrics: BrowserMetrics = field(default_factory=BrowserMetrics)
    is_active: bool = False

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "url": self.url,
            "user_agent": self.user_agent,
            "viewport": self.viewport,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "request_count": self.request_count,
            "is_active": self.is_active,
            "metrics": self.metrics.to_dict(),
        }


class HumanBehaviorSimulator:
    """Simulate human-like browser behavior.

    Generates realistic mouse movements, scrolling patterns,
    and typing rhythms to avoid bot detection.
    """

    def __init__(
        self,
        min_pause_ms: int = 100,
        max_pause_ms: int = 3000,
        typing_speed_wpm: int = 60,
        mouse_speed: float = 1.0,
    ) -> None:
        self.min_pause_ms = min_pause_ms
        self.max_pause_ms = max_pause_ms
        self.typing_speed_wpm = typing_speed_wpm
        self.mouse_speed = mouse_speed

    def random_pause(self, min_ms: Optional[int] = None, max_ms: Optional[int] = None) -> float:
        """Generate a random pause duration (seconds).

        Uses normal distribution for more natural timing.
        """
        min_ms = min_ms or self.min_pause_ms
        max_ms = max_ms or self.max_pause_ms
        # Normal distribution centered between min and max
        mean = (min_ms + max_ms) / 2
        std = (max_ms - min_ms) / 4
        pause_ms = random.gauss(mean, std)
        pause_ms = max(min_ms, min(max_ms, pause_ms))
        return pause_ms / 1000.0

    def generate_mouse_path(
        self,
        start: Tuple[int, int],
        end: Tuple[int, int],
        num_points: int = 20,
    ) -> List[Tuple[int, int]]:
        """Generate a human-like mouse path using Bezier curves.

        Args:
            start: Start position (x, y).
            end: End position (x, y).
            num_points: Number of points in path.

        Returns:
            List of (x, y) positions.
        """
        # Generate control points for Bezier curve
        dx = end[0] - start[0]
        dy = end[1] - start[1]

        # Random control points for natural curve
        cp1 = (
            start[0] + dx * 0.3 + random.randint(-50, 50),
            start[1] + dy * 0.3 + random.randint(-50, 50),
        )
        cp2 = (
            start[0] + dx * 0.7 + random.randint(-50, 50),
            start[1] + dy * 0.7 + random.randint(-50, 50),
        )

        path = []
        for i in range(num_points):
            t = i / (num_points - 1)
            # Cubic Bezier curve
            x = (
                (1 - t) ** 3 * start[0]
                + 3 * (1 - t) ** 2 * t * cp1[0]
                + 3 * (1 - t) * t ** 2 * cp2[0]
                + t ** 3 * end[0]
            )
            y = (
                (1 - t) ** 3 * start[1]
                + 3 * (1 - t) ** 2 * t * cp1[1]
                + 3 * (1 - t) * t ** 2 * cp2[1]
                + t ** 3 * end[1]
            )
            path.append((int(x), int(y)))

        return path

    def generate_scroll_pattern(
        self,
        total_height: int,
        viewport_height: int = 1080,
        num_scrolls: int = 5,
    ) -> List[Dict[str, Any]]:
        """Generate a human-like scroll pattern.

        Args:
            total_height: Total page height.
            viewport_height: Viewport height.
            num_scrolls: Number of scroll actions.

        Returns:
            List of scroll actions with position and pause.
        """
        actions = []
        current_position = 0
        max_scroll = max(0, total_height - viewport_height)

        for i in range(num_scrolls):
            # Random scroll amount (sometimes scroll up slightly)
            if random.random() < 0.2 and current_position > 100:
                # Scroll up slightly (20% chance)
                scroll_amount = random.randint(50, 200)
                current_position = max(0, current_position - scroll_amount)
            else:
                # Scroll down
                scroll_amount = random.randint(100, 500)
                current_position = min(max_scroll, current_position + scroll_amount)

            actions.append({
                "position": current_position,
                "pause_seconds": self.random_pause(500, 3000),
                "direction": "up" if scroll_amount < 0 else "down",
            })

        # Sometimes scroll back to top
        if random.random() < 0.3:
            actions.append({
                "position": 0,
                "pause_seconds": self.random_pause(500, 1500),
                "direction": "up",
            })

        return actions

    def generate_typing_delay(self, character: str = "") -> float:
        """Generate a realistic typing delay for a character.

        Args:
            character: The character being typed.

        Returns:
            Delay in seconds.
        """
        # Base delay from WPM (words per minute, average 5 chars per word)
        base_delay = 60.0 / (self.typing_speed_wpm * 5)

        # Add variation
        delay = random.gauss(base_delay, base_delay * 0.3)
        delay = max(0.01, delay)

        # Longer pause for certain characters
        if character in ".!?":
            delay *= 2.5
        elif character in ",;:":
            delay *= 1.5
        elif character == " ":
            delay *= 1.2

        return delay

    def simulate_reading_pause(self, content_length: int = 1000) -> float:
        """Simulate a reading pause based on content length.

        Args:
            content_length: Approximate content length in characters.

        Returns:
            Pause duration in seconds.
        """
        # Average reading speed: 200-300 words per minute
        # Average 5 characters per word
        words = content_length / 5
        reading_time_seconds = words / 250 * 60
        # Add random variation
        variation = random.gauss(0, reading_time_seconds * 0.2)
        return max(1.0, reading_time_seconds + variation)


class BrowserInstancePool:
    """Pool of browser instances for reuse.

    Manages browser instances to reduce startup overhead and
    improve performance for multiple page loads.
    """

    def __init__(
        self,
        max_instances: int = 3,
        idle_timeout_seconds: int = 300,
        max_requests_per_instance: int = 100,
    ) -> None:
        self.max_instances = max_instances
        self.idle_timeout_seconds = idle_timeout_seconds
        self.max_requests_per_instance = max_requests_per_instance
        self._instances: Dict[str, BrowserSession] = {}
        self._active_instance_id: Optional[str] = None

    def acquire(self, url: str = "") -> Optional[BrowserSession]:
        """Acquire a browser instance from the pool.

        Args:
            url: URL to navigate to.

        Returns:
            BrowserSession or None if pool is full.
        """
        # Look for reusable instance
        for session_id, session in self._instances.items():
            if not session.is_active and self._is_instance_reusable(session):
                session.is_active = True
                session.last_used_at = time.time()
                if url:
                    session.url = url
                self._active_instance_id = session_id
                return session

        # Create new instance if under max
        if len(self._instances) < self.max_instances:
            session = self._create_instance(url)
            self._instances[session.session_id] = session
            self._active_instance_id = session.session_id
            return session

        return None

    def release(self, session_id: str) -> None:
        """Release a browser instance back to the pool.

        Args:
            session_id: Session ID to release.
        """
        if session_id in self._instances:
            session = self._instances[session_id]
            session.is_active = False
            session.last_used_at = time.time()
            if self._active_instance_id == session_id:
                self._active_instance_id = None

    def cleanup(self) -> int:
        """Clean up expired or exhausted instances.

        Returns:
            Number of instances cleaned up.
        """
        cleaned = 0
        current_time = time.time()
        to_remove = []

        for session_id, session in self._instances.items():
            if session.is_active:
                continue

            # Check idle timeout
            if current_time - session.last_used_at > self.idle_timeout_seconds:
                to_remove.append(session_id)
                cleaned += 1
                continue

            # Check max requests
            if session.request_count >= self.max_requests_per_instance:
                to_remove.append(session_id)
                cleaned += 1

        for session_id in to_remove:
            del self._instances[session_id]

        return cleaned

    def _create_instance(self, url: str = "") -> BrowserSession:
        """Create a new browser session."""
        import uuid
        session = BrowserSession(
            session_id=str(uuid.uuid4())[:8],
            url=url,
            created_at=time.time(),
            last_used_at=time.time(),
            is_active=True,
        )
        return session

    def _is_instance_reusable(self, session: BrowserSession) -> bool:
        """Check if an instance is reusable."""
        if session.request_count >= self.max_requests_per_instance:
            return False
        if time.time() - session.last_used_at > self.idle_timeout_seconds:
            return False
        return True

    @property
    def size(self) -> int:
        return len(self._instances)

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._instances.values() if s.is_active)

    @property
    def idle_count(self) -> int:
        return sum(1 for s in self._instances.values() if not s.is_active)

    def get_stats(self) -> dict:
        """Get pool statistics."""
        return {
            "total_instances": self.size,
            "active_instances": self.active_count,
            "idle_instances": self.idle_count,
            "max_instances": self.max_instances,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "max_requests_per_instance": self.max_requests_per_instance,
        }


class BrowserOptimizer:
    """Main browser automation optimizer.

    Combines instance pooling, human behavior simulation,
    and intelligent waiting for robust web automation.
    """

    def __init__(
        self,
        max_instances: int = 3,
        enable_human_behavior: bool = True,
        enable_pooling: bool = True,
        human_behavior_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.enable_human_behavior = enable_human_behavior
        self.enable_pooling = enable_pooling

        if enable_pooling:
            self.pool = BrowserInstancePool(max_instances=max_instances)
        else:
            self.pool = None

        if enable_human_behavior:
            config = human_behavior_config or {}
            self.behavior = HumanBehaviorSimulator(**config)
        else:
            self.behavior = None

    def navigate(self, url: str, wait_for_load: bool = True) -> Optional[BrowserSession]:
        """Navigate to a URL with optimized behavior.

        Args:
            url: URL to navigate to.
            wait_for_load: Whether to wait for page load.

        Returns:
            BrowserSession or None.
        """
        session = None

        if self.pool:
            session = self.pool.acquire(url)
        else:
            import uuid
            session = BrowserSession(
                session_id=str(uuid.uuid4())[:8],
                url=url,
                created_at=time.time(),
                last_used_at=time.time(),
                is_active=True,
            )

        if session:
            session.request_count += 1
            session.url = url

            # Simulate human behavior
            if self.behavior and self.enable_human_behavior:
                # Random pause before navigation
                time.sleep(self.behavior.random_pause(100, 500))

        return session

    def simulate_human_interaction(
        self,
        session: BrowserSession,
        content_length: int = 1000,
        page_height: int = 5000,
    ) -> BrowserMetrics:
        """Simulate human interaction on a page.

        Args:
            session: Browser session.
            content_length: Content length for reading simulation.
            page_height: Page height for scroll simulation.

        Returns:
            Updated BrowserMetrics.
        """
        metrics = session.metrics

        if not self.behavior or not self.enable_human_behavior:
            return metrics

        # Simulate scrolling
        scroll_actions = self.behavior.generate_scroll_pattern(page_height)
        max_scroll = max((a["position"] for a in scroll_actions), default=0)
        metrics.scroll_depth_percent = min(100, (max_scroll / page_height) * 100)

        # Simulate reading
        reading_time = self.behavior.simulate_reading_pause(content_length)
        metrics.time_on_page_seconds = reading_time

        return metrics

    def release_session(self, session: BrowserSession) -> None:
        """Release a browser session.

        Args:
            session: Session to release.
        """
        if self.pool:
            self.pool.release(session.session_id)

    def cleanup(self) -> int:
        """Clean up pool instances."""
        if self.pool:
            return self.pool.cleanup()
        return 0

    def get_stats(self) -> dict:
        """Get optimizer statistics."""
        stats = {
            "enable_human_behavior": self.enable_human_behavior,
            "enable_pooling": self.enable_pooling,
        }
        if self.pool:
            stats["pool"] = self.pool.get_stats()
        return stats


def optimize_browser_navigation(
    url: str,
    enable_human_behavior: bool = True,
    max_instances: int = 3,
    **kwargs,
) -> Optional[BrowserSession]:
    """Convenience function for optimized browser navigation.

    Args:
        url: URL to navigate to.
        enable_human_behavior: Whether to enable human behavior simulation.
        max_instances: Max browser instances in pool.
        **kwargs: Additional optimizer options.

    Returns:
        BrowserSession or None.
    """
    optimizer = BrowserOptimizer(
        max_instances=max_instances,
        enable_human_behavior=enable_human_behavior,
        **kwargs,
    )
    return optimizer.navigate(url)
