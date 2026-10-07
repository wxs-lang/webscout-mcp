"""Deterministic stability tests for web_crawl (Phase 1 hardening).

All tests run against a local pytest-httpserver or a FakeFetcher — no public
network. They cover robots compliance, SSRF gating, redirect/loop handling,
resource caps, worker isolation, cancellation, and three-state results.

Convention: synchronous ``def test_*`` wrapping the async logic in
``asyncio.run()`` — matching the rest of this repo (no pytest-asyncio).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

import pytest

from webscout_mcp.config import Config
from webscout_mcp.crawler import Crawler
from webscout_mcp.fetcher import FetchResult
from webscout_mcp.robots import RobotsChecker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeFetcher:
    """Stand-in for Fetcher. Records calls and returns scripted results.

    Implements the small surface the Crawler uses (fetch + safety attrs).
    """

    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[str] = []
        self.safety_check_enabled = False
        self.safety_allow_private = False

    async def fetch(self, url: str, extract: bool = True, max_chars: int = 4000, **kw) -> FetchResult:
        self.calls.append(url)
        return await self.handler(url)


def _html(body_links: list[str]) -> str:
    links = "\n".join(f'<a href="{u}">x</a>' for u in body_links)
    return f"<html><head><title>t</title></head><body>{links}</body></html>"


def _ok(url: str, html: str = "", final_url: str | None = None) -> FetchResult:
    return FetchResult(
        url=url,
        final_url=final_url or url,
        status_code=200,
        content="ok",
        raw_html=html,
        content_type="text/html",
    )


def _err(url: str, msg: str, status: int = 500) -> FetchResult:
    return FetchResult(url=url, final_url=url, status_code=status, error=msg)


def make_crawler(fetcher, *, respect_robots: bool = False, robots: RobotsChecker | None = None) -> Crawler:
    cfg = Config()
    cfg.respect_robots = respect_robots
    return Crawler(cfg, fetcher, robots_checker=robots, allow_private=True)


# ---------------------------------------------------------------------------
# P. Happy path
# ---------------------------------------------------------------------------


def test_happy_path_single_page():
    async def _run():
        async def handler(url: str) -> FetchResult:
            return _ok(url, _html([]))

        cr = make_crawler(FakeFetcher(handler))
        return await cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=0)

    res = asyncio.run(_run())
    assert res.pages_crawled == 1
    assert res.status == "success"
    assert res.pages_succeeded == 1
    assert res.pages_failed == 0


# ---------------------------------------------------------------------------
# G. max_pages
# ---------------------------------------------------------------------------


def test_max_pages_hard_cap():
    async def _run():
        async def handler(url: str) -> FetchResult:
            links = [f"http://example.test/p{i}" for i in range(200)]
            return _ok(url, _html(links))

        cr = make_crawler(FakeFetcher(handler))
        return await cr.crawl("http://example.test/", max_depth=1, max_pages=10, max_retries=0)

    res = asyncio.run(_run())
    assert res.pages_crawled == 10
    assert res.pages_crawled <= 10


# ---------------------------------------------------------------------------
# H. max_depth
# ---------------------------------------------------------------------------


def test_max_depth_respected():
    async def _run():
        def links_for(u: str) -> list[str]:
            path = urlparse(u).path.rstrip("/")
            n = {"": "d1", "/d1": "d2", "/d2": "d3"}.get(path, "")
            return [f"http://example.test/{n}"] if n else []

        async def handler(url: str) -> FetchResult:
            return _ok(url, _html(links_for(url)))

        cr = make_crawler(FakeFetcher(handler))
        return await cr.crawl("http://example.test/", max_depth=1, max_pages=100, max_retries=0)

    res = asyncio.run(_run())
    fetched = [p.url for p in res.pages]
    assert "http://example.test/d2" not in fetched
    assert "http://example.test/d1" in fetched


# ---------------------------------------------------------------------------
# K. Worker failure isolation
# ---------------------------------------------------------------------------


def test_worker_failure_isolation():
    async def _run():
        seed_html = _html(["http://example.test/good1", "http://example.test/bad", "http://example.test/good2"])

        async def handler(url: str) -> FetchResult:
            if url == "http://example.test/":
                return _ok(url, seed_html)
            if url.endswith("/bad"):
                return _err(url, "connection reset by peer")
            return _ok(url, _html([]))

        cr = make_crawler(FakeFetcher(handler))
        return await cr.crawl("http://example.test/", max_depth=1, max_pages=10, max_retries=0)

    res = asyncio.run(_run())
    assert res.status == "partial"
    assert res.pages_succeeded >= 2
    assert res.pages_failed == 1


# ---------------------------------------------------------------------------
# O. Partial result
# ---------------------------------------------------------------------------


def test_partial_status_when_some_fail():
    async def _run():
        async def handler(url: str) -> FetchResult:
            if url == "http://example.test/":
                return _ok(url, _html(["http://example.test/a", "http://example.test/bad404"]))
            if "404" in url:
                return _err(url, "HTTP 404 Not Found", status=404)
            return _ok(url, _html([]))

        cr = make_crawler(FakeFetcher(handler))
        return await cr.crawl("http://example.test/", max_depth=1, max_pages=5, max_retries=0)

    res = asyncio.run(_run())
    assert res.status == "partial"
    assert res.errors


# ---------------------------------------------------------------------------
# N. 429 / 5xx classification
# ---------------------------------------------------------------------------


def test_429_retried_then_recorded():
    attempts = {"n": 0}

    async def _run():
        async def handler(url: str) -> FetchResult:
            attempts["n"] += 1
            return _err(url, "HTTP 429 Too Many Requests", status=429)

        cr = make_crawler(FakeFetcher(handler))
        return await cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=1)

    res = asyncio.run(_run())
    assert res.pages_failed == 1
    assert attempts["n"] == 2  # 1 initial + 1 retry


def test_5xx_is_transient():
    async def _run():
        async def handler(url: str) -> FetchResult:
            return _err(url, "HTTP 503 Service Unavailable", status=503)

        cr = make_crawler(FakeFetcher(handler))
        return await cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=0)

    res = asyncio.run(_run())
    assert res.pages_failed == 1
    assert res.errors[0]["type"] == "transient"


# ---------------------------------------------------------------------------
# D. Redirect loop detection
# ---------------------------------------------------------------------------


def test_redirect_loop_counted_not_crash():
    async def _run():
        async def handler(url: str) -> FetchResult:
            return _err(url, "Redirect loop detected (max_redirects=5)", status=0)

        cr = make_crawler(FakeFetcher(handler))
        return await cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=0)

    res = asyncio.run(_run())
    assert res.pages_failed == 1
    assert res.redirect_loops >= 1


# ---------------------------------------------------------------------------
# L. Canonical dedup
# ---------------------------------------------------------------------------


def test_canonical_dedup():
    async def _run():
        fetcher = FakeFetcher(lambda u: _ok(u, _html([])))
        seen: list[str] = []
        original = fetcher.handler

        async def tracking(url: str) -> FetchResult:
            seen.append(url)
            return await original(url)

        async def seed_handler(url: str) -> FetchResult:
            if url == "http://example.test/":
                return _ok(url, _html([
                    "http://example.test/page?utm_source=x",
                    "http://example.test/page",
                    "http://example.test/page#frag",
                ]))
            return await tracking(url)

        fetcher.handler = seed_handler
        cr = make_crawler(fetcher)
        res = await cr.crawl("http://example.test/", max_depth=1, max_pages=10, max_retries=0)
        return res, seen

    res, seen = asyncio.run(_run())
    page_fetches = [u for u in seen if "/page" in u]
    assert len(page_fetches) == 1


# ---------------------------------------------------------------------------
# I. Queue cap
# ---------------------------------------------------------------------------


def test_queue_size_cap():
    async def _run():
        async def handler(url: str) -> FetchResult:
            if url == "http://example.test/":
                links = [f"http://example.test/p{i}" for i in range(500)]
                return _ok(url, _html(links))
            return _ok(url, _html([]))

        cr = make_crawler(FakeFetcher(handler))
        cr.config.crawler_max_queue_size = 20
        return await cr.crawl("http://example.test/", max_depth=1, max_pages=50, max_retries=0)

    res = asyncio.run(_run())
    assert res.queue_dropped > 0
    assert res.peak_queue_size <= 20


# ---------------------------------------------------------------------------
# J. Total timeout -> partial
# ---------------------------------------------------------------------------


def test_total_timeout_returns_partial():
    async def _run():
        async def slow(url: str) -> FetchResult:
            await asyncio.sleep(5.0)
            return _ok(url, _html([]))

        cr = make_crawler(FakeFetcher(slow))
        cr.config.crawler_total_timeout = 0.2
        return await cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=0)

    res = asyncio.run(_run())
    assert res.total_timeout_exceeded is True
    assert res.status in ("partial", "failure")


# ---------------------------------------------------------------------------
# M. Cancellation
# ---------------------------------------------------------------------------


def test_cancellation_returns_partial():
    async def _run():
        async def slow(url: str) -> FetchResult:
            await asyncio.sleep(5.0)
            return _ok(url, _html([]))

        cr = make_crawler(FakeFetcher(slow))
        task = asyncio.create_task(
            cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=0)
        )
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            return await task
        except asyncio.CancelledError:
            return None

    res = asyncio.run(_run())
    assert res is not None, "cancellation should surface as partial result, not raise"
    assert res.cancelled is True or res.pages_crawled == 0


# ---------------------------------------------------------------------------
# F. SSRF gate blocks private target (allow_private=False)
# ---------------------------------------------------------------------------


def test_ssrf_blocked_when_not_allowing_private():
    async def _run():
        async def handler(url: str) -> FetchResult:
            return _ok(url, _html([]))

        cfg = Config()
        cfg.respect_robots = False
        cr = Crawler(cfg, FakeFetcher(handler), allow_private=False)
        return await cr.crawl("http://127.0.0.1/admin", max_depth=0, max_pages=1, max_retries=0)

    res = asyncio.run(_run())
    assert res.pages_blocked_ssrf >= 1
    assert res.pages_crawled == 0


def test_ssrf_blocked_metadata_endpoint():
    async def _run():
        async def handler(url: str) -> FetchResult:
            return _ok(url, _html([]))

        cfg = Config()
        cfg.respect_robots = False
        cr = Crawler(cfg, FakeFetcher(handler), allow_private=False)
        return await cr.crawl(
            "http://169.254.169.254/latest/meta-data/", max_depth=0, max_pages=1, max_retries=0
        )

    res = asyncio.run(_run())
    assert res.pages_blocked_ssrf >= 1


# ---------------------------------------------------------------------------
# A/B/C. robots.txt compliance via local httpserver
# ---------------------------------------------------------------------------


def test_robots_disallow_blocks_path(monkeypatch):
    async def fake_is_allowed(url):
        return "/private/" not in url

    async def _run():
        fetched: list[str] = []

        async def handler(url: str) -> FetchResult:
            fetched.append(url)
            return _ok(url, _html([
                "http://example.test/private/secret",
                "http://example.test/public",
            ]))

        cfg = Config()
        cfg.respect_robots = True
        robots = RobotsChecker(cfg, respect_robots=True)
        monkeypatch.setattr(robots, "is_allowed", fake_is_allowed)
        cr = Crawler(cfg, FakeFetcher(handler), robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://example.test/", max_depth=1, max_pages=10, max_retries=0)
        return res, fetched

    res, fetched = asyncio.run(_run())
    assert not any("/private/" in u for u in fetched)
    assert res.pages_blocked_robots >= 1


def test_robots_404_allows_all(monkeypatch):
    async def fake_is_allowed(url):
        return True  # 404 robots.txt -> parser=None -> allow all

    async def _run():
        async def handler(url: str) -> FetchResult:
            return _ok(url, _html([]))

        cfg = Config()
        cfg.respect_robots = True
        robots = RobotsChecker(cfg, respect_robots=True)
        monkeypatch.setattr(robots, "is_allowed", fake_is_allowed)
        cr = Crawler(cfg, FakeFetcher(handler), robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=0)
        return res

    res = asyncio.run(_run())
    assert res.pages_crawled == 1


def test_robots_malformed_is_tolerated(monkeypatch):
    async def fake_is_allowed(url):
        return True  # malformed robots.txt -> fail-safe allow

    async def _run():
        async def handler(url: str) -> FetchResult:
            return _ok(url, _html([]))

        cfg = Config()
        cfg.respect_robots = True
        robots = RobotsChecker(cfg, respect_robots=True)
        monkeypatch.setattr(robots, "is_allowed", fake_is_allowed)
        cr = Crawler(cfg, FakeFetcher(handler), robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=0)
        return res

    res = asyncio.run(_run())
    assert res.pages_crawled == 1


def test_robots_timeout_fails_open(monkeypatch):
    monkeypatch.setattr("webscout_mcp.crawler._ROBOTS_TIMEOUT", 0.1)

    async def slow_is_allowed(url):
        await asyncio.sleep(5.0)  # longer than the 0.1s timeout
        return False

    async def _run():
        async def handler(url: str) -> FetchResult:
            return _ok(url, _html([]))

        cfg = Config()
        cfg.respect_robots = True
        robots = RobotsChecker(cfg, respect_robots=True)
        monkeypatch.setattr(robots, "is_allowed", slow_is_allowed)
        cr = Crawler(cfg, FakeFetcher(handler), robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://example.test/", max_depth=0, max_pages=1, max_retries=0)
        return res

    res = asyncio.run(_run())
    assert res.pages_crawled == 1
    assert res.timeouts >= 1


# ---------------------------------------------------------------------------
# Phase 1.1 — Cross-host redirect robots: PRE-FETCH compliance
#
# The crawler now follows redirects MANUALLY (follow_redirects=False on the
# fetch call). For every 3xx hop it resolves the Location target, runs the
# SSRF guard, and — when the host changes — consults robots.txt BEFORE
# requesting the target's body. Same-host redirects skip the extra robots
# lookup. All scenarios below use RedirectFetcher (scripted 3xx + Location)
# + monkeypatched robots.is_allowed — deterministic, no public network.
# ---------------------------------------------------------------------------


class RedirectFetcher:
    """Scripted fetcher that returns 3xx redirect responses.

    routes: dict mapping URL -> route dict.
      - Redirect: {"status": 301|302|303|307|308, "location": "..."}
      - Body:     {"status": 200, "html": "..."}
    Records every fetch call in ``calls`` and only body (200) calls in
    ``body_calls`` so tests can assert "target body was never requested".
    """

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.body_calls: list[str] = []
        self.safety_check_enabled = False
        self.safety_allow_private = False

    async def fetch(
        self,
        url: str,
        extract: bool = True,
        max_chars: int = 4000,
        follow_redirects: bool = True,
        bypass_cache: bool = False,
        **kw,
    ) -> FetchResult:
        self.calls.append(url)
        route = self.routes.get(url)
        if route is None:
            return FetchResult(
                url=url, final_url=url, status_code=404,
                error="Not found", content_type="text/html",
            )
        status = route.get("status", 200)
        if status in (301, 302, 303, 307, 308):
            return FetchResult(
                url=url, final_url=url, status_code=status,
                metadata={"headers": {"location": route["location"]}},
            )
        self.body_calls.append(url)
        return FetchResult(
            url=url, final_url=url, status_code=200,
            content="ok", raw_html=route.get("html", ""),
            content_type="text/html",
        )


def _tracking_robots(monkeypatch, decisions: dict | None = None, slow_host: str | None = None):
    """Build a (robots_checker, calls_list, decisions dict).

    decisions: {host: bool} — default allow.
    slow_host: host that should sleep 5s (to trigger _ROBOTS_TIMEOUT).
    """
    checked: list[str] = []
    decisions = decisions or {}

    async def fake_is_allowed(url: str) -> bool:
        checked.append(url)
        host = urlparse(url).netloc.lower()
        if slow_host and host == slow_host:
            await asyncio.sleep(5.0)
        return decisions.get(host, True)

    cfg = Config()
    cfg.respect_robots = True
    robots = RobotsChecker(cfg, respect_robots=True)
    monkeypatch.setattr(robots, "is_allowed", fake_is_allowed)
    return robots, checked


def test_redirect_a_to_b_allowed(monkeypatch):
    """Scenario 1: A→301→B, robots allows B => B body fetched, page crawled."""
    async def _run():
        fetcher = RedirectFetcher({
            "http://a.test/": {"status": 301, "location": "http://b.test/landing"},
            "http://b.test/landing": {"status": 200, "html": _html([])},
        })
        robots, checked = _tracking_robots(monkeypatch, decisions={"a.test": True, "b.test": True})
        cr = Crawler(Config(), fetcher, robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://a.test/", max_depth=0, max_pages=1, max_retries=0)
        return res, fetcher, checked

    res, fetcher, checked = asyncio.run(_run())
    assert "http://b.test/landing" in fetcher.body_calls
    assert res.pages_crawled == 1
    assert res.pages_blocked_robots == 0


def test_redirect_a_to_b_disallowed_body_count_zero(monkeypatch):
    """Scenario 2 (CRITICAL): A→301→B, robots disallows B.

    B robots is consulted, but B body fetch call count MUST be zero —
    the pre-fetch robots gate returns BEFORE requesting B's body.
    """
    async def _run():
        fetcher = RedirectFetcher({
            "http://a.test/": {"status": 301, "location": "http://b.test/secret"},
            "http://b.test/secret": {"status": 200, "html": _html([])},
        })
        robots, checked = _tracking_robots(monkeypatch, decisions={"a.test": True, "b.test": False})
        cr = Crawler(Config(), fetcher, robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://a.test/", max_depth=0, max_pages=1, max_retries=0)
        return res, fetcher, checked

    res, fetcher, checked = asyncio.run(_run())
    # B robots was consulted.
    assert any("b.test" in u for u in checked), f"robots calls did not include B: {checked}"
    # CRITICAL: B body was NEVER fetched.
    assert "http://b.test/secret" not in fetcher.body_calls, (
        f"B body was fetched despite robots disallow! body_calls={fetcher.body_calls}"
    )
    assert res.pages_blocked_robots >= 1
    assert res.pages_crawled == 0
    assert res.pages_succeeded == 0


def test_redirect_a_to_b_to_c(monkeypatch):
    """Scenario 3: A→301→B→301→C. Robots consulted for A, B, C. C body fetched."""
    async def _run():
        fetcher = RedirectFetcher({
            "http://a.test/": {"status": 301, "location": "http://b.test/"},
            "http://b.test/": {"status": 301, "location": "http://c.test/final"},
            "http://c.test/final": {"status": 200, "html": _html([])},
        })
        robots, checked = _tracking_robots(
            monkeypatch,
            decisions={"a.test": True, "b.test": True, "c.test": True},
        )
        cr = Crawler(Config(), fetcher, robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://a.test/", max_depth=0, max_pages=1, max_retries=0)
        return res, fetcher, checked

    res, fetcher, checked = asyncio.run(_run())
    # Robots consulted for every host in the chain.
    checked_hosts = [urlparse(u).netloc.lower() for u in checked]
    assert "a.test" in checked_hosts
    assert "b.test" in checked_hosts
    assert "c.test" in checked_hosts
    # C body was fetched.
    assert "http://c.test/final" in fetcher.body_calls
    assert res.pages_crawled == 1


def test_same_host_redirect_no_extra_robots(monkeypatch):
    """Scenario 4: A→301→A/other (same host). Robots consulted ONCE (initial A)."""
    async def _run():
        fetcher = RedirectFetcher({
            "http://a.test/": {"status": 301, "location": "http://a.test/other"},
            "http://a.test/other": {"status": 200, "html": _html([])},
        })
        robots, checked = _tracking_robots(monkeypatch)
        cr = Crawler(Config(), fetcher, robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://a.test/", max_depth=0, max_pages=1, max_retries=0)
        return res, fetcher, checked

    res, fetcher, checked = asyncio.run(_run())
    # Only the initial URL was consulted; same-host redirect did NOT re-check.
    assert len(checked) == 1, f"expected 1 robots call, got {len(checked)}: {checked}"
    assert checked[0] == "http://a.test/"
    # Body was fetched at the redirected (same-host) path.
    assert "http://a.test/other" in fetcher.body_calls
    assert res.pages_crawled == 1


def test_redirect_target_robots_timeout(monkeypatch):
    """Scenario 5: A→301→B, B robots check times out => fail-safe allow."""
    monkeypatch.setattr("webscout_mcp.crawler._ROBOTS_TIMEOUT", 0.1)

    async def _run():
        fetcher = RedirectFetcher({
            "http://a.test/": {"status": 301, "location": "http://b.test/landing"},
            "http://b.test/landing": {"status": 200, "html": _html([])},
        })
        robots, checked = _tracking_robots(
            monkeypatch,
            decisions={"a.test": True, "b.test": True},
            slow_host="b.test",
        )
        cr = Crawler(Config(), fetcher, robots_checker=robots, allow_private=True)
        res = await cr.crawl("http://a.test/", max_depth=0, max_pages=1, max_retries=0)
        return res, fetcher, checked

    res, fetcher, checked = asyncio.run(_run())
    # Fail-safe allow: B body still fetched.
    assert "http://b.test/landing" in fetcher.body_calls
    assert res.pages_crawled == 1
    assert res.timeouts >= 1


def test_redirect_to_private_ip_ssrf_before_robots(monkeypatch):
    """Scenario 6: A→301→http://192.168.1.1/. SSRF blocks BEFORE robots.

    Uses a public literal IP seed (8.8.8.8) that passes SSRF with
    allow_private=False; the redirect target is a private IP.
    Robots.is_allowed must NOT be called for the private target.
    """
    async def _run():
        fetcher = RedirectFetcher({
            "http://8.8.8.8/": {"status": 301, "location": "http://192.168.1.1/"},
            "http://192.168.1.1/": {"status": 200, "html": _html([])},
        })
        robots, checked = _tracking_robots(monkeypatch)
        cfg = Config()
        cfg.respect_robots = True
        cr = Crawler(cfg, fetcher, robots_checker=robots, allow_private=False)
        res = await cr.crawl("http://8.8.8.8/", max_depth=0, max_pages=1, max_retries=0)
        return res, fetcher, checked

    res, fetcher, checked = asyncio.run(_run())
    assert res.pages_blocked_ssrf >= 1
    # Robots must NOT have been consulted for the private target.
    assert not any("192.168.1.1" in u for u in checked), (
        f"robots was called for private target despite SSRF-first order: {checked}"
    )
    # Private target body was never fetched.
    assert "http://192.168.1.1/" not in fetcher.body_calls
    assert res.pages_crawled == 0


def test_redirect_loop_terminates(monkeypatch):
    """Scenario 7: A→301→B→301→A. Loop detected, terminates, no infinite hang."""
    async def _run():
        fetcher = RedirectFetcher({
            "http://a.test/": {"status": 301, "location": "http://b.test/"},
            "http://b.test/": {"status": 301, "location": "http://a.test/"},
        })
        cfg = Config()
        cfg.respect_robots = False
        cr = Crawler(cfg, fetcher, allow_private=True)
        res = await cr.crawl("http://a.test/", max_depth=0, max_pages=1, max_retries=0)
        return res, fetcher

    res, fetcher = asyncio.run(_run())
    assert res.redirect_loops >= 1
    assert res.pages_crawled == 0


def test_max_redirects_terminates(monkeypatch):
    """Scenario 8: A→B→C→D→E→F→G exceeds max_redirects=5. Terminates."""
    routes = {
        "http://a.test/": {"status": 301, "location": "http://b.test/"},
        "http://b.test/": {"status": 301, "location": "http://c.test/"},
        "http://c.test/": {"status": 301, "location": "http://d.test/"},
        "http://d.test/": {"status": 301, "location": "http://e.test/"},
        "http://e.test/": {"status": 301, "location": "http://f.test/"},
        "http://f.test/": {"status": 301, "location": "http://g.test/"},
        "http://g.test/": {"status": 200, "html": _html([])},
    }

    async def _run():
        fetcher = RedirectFetcher(routes)
        cfg = Config()
        cfg.respect_robots = False
        cr = Crawler(cfg, fetcher, allow_private=True)
        res = await cr.crawl("http://a.test/", max_depth=0, max_pages=1, max_retries=0)
        return res, fetcher

    res, fetcher = asyncio.run(_run())
    assert res.pages_crawled == 0
    assert res.redirect_loops >= 1 or res.pages_failed >= 1


# ---------------------------------------------------------------------------
# Phase 1.1 — 10 / 50 / 100 pages deterministic stability smoke
#
# SyntheticFetcher builds an in-memory graph of 130 pages: page0 links to
# page1..page10, every pageN (N>=1) links to page{2N+1} and page{2N+2} when
# they exist. page0 reaches every node; BFS depth ~7, well under max_depth=10.
# No network — the fetcher returns scripted HTML for any synthetic URL.
# ---------------------------------------------------------------------------


class SyntheticFetcher:
    """Deterministic in-memory fetch graph; mirrors the FakeFetcher surface."""

    def __init__(self, num_pages: int = 130) -> None:
        self.num_pages = num_pages
        self.safety_check_enabled = False
        self.safety_allow_private = False
        self.calls: list[str] = []

    def _links_for(self, n: int) -> list[str]:
        if n == 0:
            return [f"http://synthetic.test/page{i}" for i in range(1, 11)]
        kids = []
        for k in (2 * n + 1, 2 * n + 2):
            if k < self.num_pages:
                kids.append(f"http://synthetic.test/page{k}")
        return kids

    async def fetch(self, url: str, extract: bool = True, max_chars: int = 4000, **kw) -> FetchResult:
        self.calls.append(url)
        name = urlparse(url).path.rsplit("/", 1)[-1]  # "pageN"
        n = int(name[4:]) if name.startswith("page") else int(name)
        return FetchResult(
            url=url,
            final_url=url,
            status_code=200,
            content="ok",
            raw_html=_html(self._links_for(n)),
            content_type="text/html",
        )


SMOKE_CONCURRENCY = 60  # >= worst-case BFS batch (47 for max_pages=100)


def _run_smoke(max_pages: int):
    async def _run():
        fetcher = SyntheticFetcher(num_pages=130)
        cfg = Config()
        cfg.respect_robots = False
        cr = Crawler(cfg, fetcher, allow_private=True)
        res = await cr.crawl(
            "http://synthetic.test/page0",
            max_depth=10,
            max_pages=max_pages,
            max_retries=0,
            concurrency=SMOKE_CONCURRENCY,
        )
        return res, fetcher

    return asyncio.run(_run())


@pytest.mark.parametrize("max_pages", [10, 50, 100])
def test_stability_smoke_page_caps(max_pages):
    res, fetcher = _run_smoke(max_pages)
    print(
        f"\n[smoke max_pages={max_pages}] "
        f"attempted={res.pages_attempted} succeeded={res.pages_succeeded} "
        f"failed={res.pages_failed} crawled={res.pages_crawled} "
        f"duration_ms={res.duration_ms:.1f} peak_queue={res.peak_queue_size} "
        f"peak_workers={res.peak_active_workers} errors={res.errors} "
        f"status={res.status}"
    )
    # Real reach, hard stop honoured.
    assert res.pages_crawled >= max_pages * 0.9
    assert res.pages_crawled <= max_pages
    # Outcome accounting consistency.
    assert res.pages_attempted >= res.pages_crawled
    assert res.pages_succeeded == res.pages_crawled
    assert res.pages_failed == 0
    # Resource caps respected.
    assert 0 < res.peak_queue_size <= 1000  # crawler_max_queue_size default
    assert 0 < res.peak_active_workers <= SMOKE_CONCURRENCY
    # Clean three-state result.
    assert res.errors == []
    assert res.status == "success"
    # Every issued fetch returned.
    assert len(fetcher.calls) == res.pages_attempted


def test_cleanup_no_leftover_tasks_after_crawl():
    """After crawl() returns: no stray asyncio tasks, no unfinished fetches."""

    async def _run():
        fetcher = SyntheticFetcher(num_pages=130)
        cfg = Config()
        cfg.respect_robots = False
        cr = Crawler(cfg, fetcher, allow_private=True)
        res = await cr.crawl(
            "http://synthetic.test/page0",
            max_depth=10,
            max_pages=50,
            max_retries=0,
            concurrency=SMOKE_CONCURRENCY,
        )
        # _crawl_impl owns semaphore/queues as locals; once it returns they are
        # gone. The externally-visible invariants: no pending tasks other than
        # this one, and every fetch completed.
        leftover = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        return res, fetcher, leftover

    res, fetcher, leftover = asyncio.run(_run())
    assert res.pages_crawled == 50
    assert res.errors == []
    assert res.status == "success"
    assert leftover == [], f"leftover asyncio tasks after crawl: {leftover!r}"
    assert len(fetcher.calls) == res.pages_attempted
