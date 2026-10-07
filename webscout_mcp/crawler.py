"""Concurrent web crawler with depth/page limits and robots.txt compliance.

Performs a BFS crawl starting from a seed URL, fetching pages concurrently
within each depth level. Respects depth, page-count, same-domain, and
robots.txt constraints.

Stable-hardening (Phase 1, v1.6.0):
- Every URL (seed + discovered link + redirect hop) re-validated through the
  shared v1.2.3 SSRF guard (:func:`check_url_safe`). The crawl path can no
  longer bypass the safe-URL boundary that the browser-escalation path
  already enforces.
- Hard resource caps: max_pages, max_depth, concurrency, per-request timeout,
  a TOTAL crawl timeout, and a bounded discovered-URL queue.
- Three-state result: ``success`` / ``partial`` / ``failure``.
- Worker failure isolation: one bad page never kills the whole crawl.
- Deterministic dedup via :func:`canonical_url_key` (never a second canonicalizer).
- Cancellation and total-timeout aborts return a *partial* result, never an
  infinite hang.
- Observability: crawl lifecycle, page outcomes, blocks, loops, timeouts,
  peak queue/workers, duration. No cookies / tokens / sensitive query strings
  are ever recorded.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import observability as obs
from .config import Config
from .fetcher import Fetcher, FetchResult
from .logging_config import get_logger
from .robots import RobotsChecker
from .url_canonicalize import canonical_url_key
from .url_safety import check_url_safe
from .utils import normalize_url

log = get_logger(__name__)

# Cap on how many discovered-but-not-yet-fetched URLs we will hold. A dense
# page can link to thousands of URLs; without this the queue (and the visited
# set) grows unboundedly regardless of max_pages.
_DEFAULT_MAX_QUEUE = 1000
# Hard upper bound on a single crawl wall-clock. Prevents a slow site from
# pinning a worker forever.
_DEFAULT_TOTAL_TIMEOUT = 60.0
# Hard upper bound on per-URL robots.txt fetch (belt-and-suspenders on top of
# httpx's own timeout).
_ROBOTS_TIMEOUT = 10.0
# HTTP status codes that indicate a redirect we should follow manually.
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)
# Max redirect hops per page (matches httpx default).
_MAX_REDIRECTS = 5


@dataclass
class CrawlResult:
    """Result of a crawl operation."""

    seed_url: str
    pages_crawled: int = 0
    pages: list[FetchResult] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    links_found: int = 0
    skipped_robots: int = 0
    retries: int = 0
    avg_response_time: float = 0.0

    # --- Stable-hardening additions (backward-compatible; old keys untouched) ---
    status: str = "success"  # success | partial | failure
    pages_attempted: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0
    pages_blocked_robots: int = 0
    pages_blocked_ssrf: int = 0
    redirect_loops: int = 0
    timeouts: int = 0
    duration_ms: float = 0.0
    peak_queue_size: int = 0
    peak_active_workers: int = 0
    cancelled: bool = False
    total_timeout_exceeded: bool = False
    queue_dropped: int = 0

    def to_dict(self) -> dict:
        return {
            "seed_url": self.seed_url,
            "pages_crawled": self.pages_crawled,
            "links_found": self.links_found,
            "skipped_robots": self.skipped_robots,
            "retries": self.retries,
            "avg_response_time": round(self.avg_response_time, 2),
            "pages": [p.to_dict() for p in self.pages],
            "errors": self.errors,
            # New, backward-compatible metadata block.
            "status": self.status,
            "stats": {
                "pages_attempted": self.pages_attempted,
                "pages_succeeded": self.pages_succeeded,
                "pages_failed": self.pages_failed,
                "pages_blocked_robots": self.pages_blocked_robots,
                "pages_blocked_ssrf": self.pages_blocked_ssrf,
                "redirect_loops": self.redirect_loops,
                "timeouts": self.timeouts,
                "duration_ms": round(self.duration_ms, 2),
                "peak_queue_size": self.peak_queue_size,
                "peak_active_workers": self.peak_active_workers,
                "cancelled": self.cancelled,
                "total_timeout_exceeded": self.total_timeout_exceeded,
                "queue_dropped": self.queue_dropped,
            },
        }


class Crawler:
    """A concurrent, polite, bounded web crawler with retry and delay support."""

    def __init__(
        self,
        config: Config,
        fetcher: Fetcher,
        robots_checker: RobotsChecker | None = None,
        *,
        allow_private: bool | None = None,
    ) -> None:
        self.config = config
        self.fetcher = fetcher
        self.robots = robots_checker or RobotsChecker(config, respect_robots=config.respect_robots)
        self._total_response_time = 0.0
        self._response_count = 0
        # Opt-out for local/mock testing only. Production default stays False,
        # meaning loopback/private/metadata targets are blocked.
        self._allow_private = (
            allow_private
            if allow_private is not None
            else bool(getattr(config, "crawler_allow_private", False))
        )
        # Arm the per-request SSRF hook on the fetcher so every redirect hop
        # is re-validated. Best-effort: the fetcher may be a mock in tests.
        try:
            self.fetcher.safety_check_enabled = True  # type: ignore[attr-defined]
            self.fetcher.safety_allow_private = self._allow_private  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - mock fetchers have no such attrs
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def crawl(
        self,
        seed_url: str,
        max_depth: int | None = None,
        max_pages: int | None = None,
        same_domain_only: bool | None = None,
        extract: bool = True,
        concurrency: int | None = None,
        delay: float | None = None,
        max_retries: int | None = None,
    ) -> CrawlResult:
        """Crawl a website starting from seed_url.

        Returns a :class:`CrawlResult`. The crawl always terminates: it is
        bounded by max_pages, max_depth, concurrency, and a total wall-clock
        timeout. Cancellation or total-timeout aborts return a partial result.
        """
        depth = max_depth if max_depth is not None else self.config.crawler_max_depth
        page_limit = max_pages if max_pages is not None else self.config.crawler_max_pages
        same_domain = same_domain_only if same_domain_only is not None else self.config.crawler_same_domain_only
        concur = max(1, concurrency or self.config.crawler_concurrency)
        base_delay = delay if delay is not None else getattr(self.config, "crawler_delay", 0.0)
        retries = max_retries if max_retries is not None else getattr(self.config, "crawler_max_retries", 2)
        total_timeout = float(getattr(self.config, "crawler_total_timeout", _DEFAULT_TOTAL_TIMEOUT))
        max_queue = int(getattr(self.config, "crawler_max_queue_size", _DEFAULT_MAX_QUEUE))

        seed_url = normalize_url(seed_url)
        seed_domain = urlparse(seed_url).netloc.lower()
        result = CrawlResult(seed_url=seed_url)
        started = time.monotonic()
        obs.record_crawl_lifecycle("started", seed=obs.safe_host(seed_url))

        try:
            await asyncio.wait_for(
                self._crawl_impl(
                    seed_url=seed_url,
                    seed_domain=seed_domain,
                    depth=depth,
                    page_limit=page_limit,
                    same_domain=same_domain,
                    extract=extract,
                    concur=concur,
                    base_delay=base_delay,
                    retries=retries,
                    max_queue=max_queue,
                    result=result,
                ),
                timeout=total_timeout,
            )
        except asyncio.TimeoutError:
            result.total_timeout_exceeded = True
            log.warning("crawl total timeout exceeded", extra={"seed": seed_url, "timeout": total_timeout})
        except asyncio.CancelledError:
            result.cancelled = True
            log.info("crawl cancelled", extra={"seed": seed_url})
            # Always return the partial result rather than propagating, so the
            # caller gets bounded diagnostics even on cancellation.
            if result.pages_crawled == 0:
                # Swallow the cancellation so the caller still receives a
                # CrawlResult; we are not inside a task that must re-raise.
                pass

        result.duration_ms = (time.monotonic() - started) * 1000.0
        result.avg_response_time = (
            self._total_response_time / self._response_count if self._response_count > 0 else 0.0
        )

        # Three-state status.
        if result.pages_crawled == 0 and result.errors:
            result.status = "failure"
        elif result.errors or result.total_timeout_exceeded or result.cancelled:
            result.status = "partial"
        else:
            result.status = "success"

        obs.record_crawl_lifecycle(
            result.status,
            seed=obs.safe_host(seed_url),
            pages=result.pages_crawled,
            duration_ms=result.duration_ms,
        )
        log.info(
            "crawl complete",
            extra={
                "seed": seed_url,
                "status": result.status,
                "pages": result.pages_crawled,
                "errors": len(result.errors),
                "blocked_robots": result.pages_blocked_robots,
                "blocked_ssrf": result.pages_blocked_ssrf,
                "duration_ms": round(result.duration_ms, 1),
            },
        )
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    async def _crawl_impl(
        self,
        *,
        seed_url: str,
        seed_domain: str,
        depth: int,
        page_limit: int,
        same_domain: bool,
        extract: bool,
        concur: int,
        base_delay: float,
        retries: int,
        max_queue: int,
        result: CrawlResult,
    ) -> None:
        visited: set[str] = set()
        semaphore = asyncio.Semaphore(concur)
        active = 0
        current_level: deque[tuple[str, int]] = deque([(seed_url, 0)])

        while current_level and result.pages_crawled < page_limit:
            next_level: deque[tuple[str, int]] = deque()
            batch: list[tuple[str, int]] = []
            while current_level and len(batch) < (page_limit - result.pages_crawled):
                url, dep = current_level.popleft()
                key = canonical_url_key(url) or url
                if key in visited:
                    continue
                visited.add(key)
                batch.append((url, dep))
            if not batch:
                break
            log.info(
                "crawling depth level",
                extra={"depth": batch[0][1], "batch_size": len(batch), "total_crawled": result.pages_crawled},
            )

            active = len(batch)
            result.peak_active_workers = max(result.peak_active_workers, active)
            tasks = [
                self._crawl_page(url, dep, extract, semaphore, result, base_delay, retries)
                for url, dep in batch
            ]
            page_results = await asyncio.gather(*tasks, return_exceptions=True)
            for (url, dep), pr in zip(batch, page_results):
                if isinstance(pr, Exception):
                    result.pages_failed += 1
                    result.errors.append({"url": url, "depth": dep, "error": str(pr), "type": "exception"})
                    continue
                if pr is None:
                    continue
                page, links = pr
                result.pages_crawled += 1
                result.pages.append(page)
                if dep < depth:
                    new_links = self._filter_links(links, visited, same_domain, seed_domain)
                    for link in new_links:
                        if len(next_level) >= max_queue:
                            result.queue_dropped += 1
                            continue
                        next_level.append((link, dep + 1))
                    result.peak_queue_size = max(result.peak_queue_size, len(next_level))
            current_level = next_level

    def _filter_links(
        self,
        links: list[str],
        visited: set[str],
        same_domain: bool,
        seed_domain: str,
    ) -> list[str]:
        """Filter and deduplicate links."""
        filtered: list[str] = []
        seen: set[str] = set()
        for link in links:
            link = normalize_url(link)
            key = canonical_url_key(link) or link
            if key in visited or key in seen:
                continue
            if same_domain:
                link_domain = urlparse(link).netloc.lower()
                if link_domain != seed_domain:
                    continue
            parsed = urlparse(link)
            if parsed.path.endswith((".pdf", ".zip", ".tar", ".gz", ".exe", ".dmg", ".mp4", ".mp3", ".avi", ".mov")):
                continue
            if any(skip in parsed.path.lower() for skip in ["/login", "/signup", "/register", "/admin", "/logout"]):
                continue
            seen.add(key)
            filtered.append(link)
        return filtered

    async def _crawl_page(
        self,
        url: str,
        depth: int,
        extract: bool,
        semaphore: asyncio.Semaphore,
        result: CrawlResult,
        base_delay: float,
        max_retries: int,
    ) -> tuple[FetchResult, list[str]] | None:
        """Crawl a single page with robots + SSRF gates and retry support."""
        result.pages_attempted += 1

        # --- SSRF gate (initial URL; each redirect target is re-checked in
        # the manual redirect loop below) ---
        safety = await asyncio.to_thread(check_url_safe, url, allow_private=self._allow_private)
        if not safety.safe:
            result.pages_blocked_ssrf += 1
            obs.record_crawl_blocked("ssrf")
            log.debug("blocked by ssrf guard", extra={"url": obs.safe_host(url), "reason": safety.reason})
            return None

        # --- robots.txt gate (fail-safe: on error we allow, but never hang) ---
        if self.config.respect_robots:
            try:
                allowed = await asyncio.wait_for(self.robots.is_allowed(url), timeout=_ROBOTS_TIMEOUT)
                if not allowed:
                    result.skipped_robots += 1
                    result.pages_blocked_robots += 1
                    obs.record_crawl_blocked("robots")
                    log.debug("skipped by robots.txt", extra={"url": obs.safe_host(url)})
                    return None
            except asyncio.TimeoutError:
                result.timeouts += 1
                log.warning("robots.txt check timed out; allowing", extra={"url": obs.safe_host(url)})
            except Exception as exc:  # noqa: BLE001 - fail-safe allow
                log.warning("robots.txt check failed, allowing", extra={"url": obs.safe_host(url), "error": str(exc)})

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                if base_delay > 0:
                    delay = base_delay * random.uniform(0.5, 1.5) * (2**attempt)
                    await asyncio.sleep(delay)

                # === Manual redirect loop ===
                # We disable the fetcher's automatic redirect-following so we
                # can validate each redirect target's SSRF safety and robots
                # policy *before* requesting its body. This fixes the
                # cross-host robots compliance bug where a redirect to a
                # disallowed host would still have its body fetched.
                current_url = url
                visited: set[str] = set()
                redirect_count = 0

                while True:
                    async with semaphore:
                        start_time = time.monotonic()
                        page = await self.fetcher.fetch(
                            current_url,
                            extract=extract,
                            max_chars=4000,
                            follow_redirects=False,
                            bypass_cache=True,
                        )
                        elapsed = time.monotonic() - start_time
                        self._total_response_time += elapsed
                        self._response_count += 1

                    # --- Redirect: validate target BEFORE fetching its body ---
                    if page.status_code in _REDIRECT_STATUSES:
                        location = (page.metadata.get("headers") or {}).get("location")
                        if not location:
                            result.pages_failed += 1
                            result.errors.append(
                                {
                                    "url": current_url,
                                    "depth": depth,
                                    "error": f"Redirect {page.status_code} with no Location header",
                                    "type": "permanent",
                                    "attempts": attempt + 1,
                                }
                            )
                            return None

                        # Resolve relative/absolute Location against current URL.
                        target = urljoin(current_url, location)

                        # 1. SSRF validation on redirect target (before robots).
                        safety_target = await asyncio.to_thread(
                            check_url_safe, target, allow_private=self._allow_private
                        )
                        if not safety_target.safe:
                            result.pages_blocked_ssrf += 1
                            obs.record_crawl_blocked("ssrf")
                            log.debug(
                                "redirect target blocked by ssrf guard",
                                extra={
                                    "url": obs.safe_host(target),
                                    "reason": safety_target.reason,
                                },
                            )
                            return None

                        # 2. Redirect loop / max-hop validation.
                        redirect_count += 1
                        if redirect_count > _MAX_REDIRECTS:
                            result.redirect_loops += 1
                            result.pages_failed += 1
                            result.errors.append(
                                {
                                    "url": current_url,
                                    "depth": depth,
                                    "error": f"Too many redirects (> {_MAX_REDIRECTS})",
                                    "type": "permanent",
                                    "attempts": attempt + 1,
                                }
                            )
                            return None
                        if target in visited:
                            result.redirect_loops += 1
                            result.pages_failed += 1
                            result.errors.append(
                                {
                                    "url": current_url,
                                    "depth": depth,
                                    "error": "Redirect loop detected",
                                    "type": "permanent",
                                    "attempts": attempt + 1,
                                }
                            )
                            return None
                        visited.add(target)

                        # 3. Cross-host robots validation (BEFORE body request).
                        #    Only re-check when the host actually changed;
                        #    same-host redirects are already covered by the
                        #    initial robots gate.
                        if self.config.respect_robots:
                            target_host = urlparse(target).netloc.lower()
                            current_host = urlparse(current_url).netloc.lower()
                            if target_host and target_host != current_host:
                                try:
                                    allowed_target = await asyncio.wait_for(
                                        self.robots.is_allowed(target),
                                        timeout=_ROBOTS_TIMEOUT,
                                    )
                                    if not allowed_target:
                                        result.skipped_robots += 1
                                        result.pages_blocked_robots += 1
                                        obs.record_crawl_blocked("robots")
                                        log.debug(
                                            "cross-host redirect blocked by robots.txt",
                                            extra={
                                                "from": obs.safe_host(current_url),
                                                "to": obs.safe_host(target),
                                            },
                                        )
                                        # CRITICAL: do NOT request target body.
                                        return None
                                except asyncio.TimeoutError:
                                    result.timeouts += 1
                                    log.warning(
                                        "cross-host robots.txt check timed out; allowing",
                                        extra={"url": obs.safe_host(target)},
                                    )
                                except Exception as exc:  # noqa: BLE001
                                    log.warning(
                                        "cross-host robots.txt check failed, allowing",
                                        extra={"url": obs.safe_host(target), "error": str(exc)},
                                    )

                        # Follow the redirect.
                        current_url = target
                        continue

                    # --- Non-redirect response: error handling ---
                    if page.error:
                        error_type = self._classify_error(page.error)
                        if "timeout" in page.error.lower():
                            result.timeouts += 1
                        if "redirect" in page.error.lower():
                            result.redirect_loops += 1
                        if error_type == "transient" and attempt < max_retries:
                            result.retries += 1
                            last_error = page.error
                            break  # exit redirect loop, retry from start
                        result.pages_failed += 1
                        result.errors.append(
                            {
                                "url": current_url,
                                "depth": depth,
                                "error": page.error,
                                "type": error_type,
                                "attempts": attempt + 1,
                            }
                        )
                        return None

                    # --- Success: extract links from final body ---
                    page.final_url = current_url
                    links: list[str] = []
                    try:
                        if page.raw_html:
                            links = self._extract_links(page.raw_html, current_url)
                            result.links_found += len(links)
                    except Exception:  # noqa: BLE001
                        pass
                    result.pages_succeeded += 1
                    return page, links

                # Broke out of the redirect loop for a retry.
                continue

            except asyncio.CancelledError:
                # Propagate cancellation; the outer crawl loop records partial.
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt < max_retries:
                    result.retries += 1
                    continue
                result.pages_failed += 1
                result.errors.append(
                    {
                        "url": url,
                        "depth": depth,
                        "error": str(exc),
                        "type": "exception",
                        "attempts": attempt + 1,
                    }
                )
                return None

        if last_error:
            result.pages_failed += 1
            result.errors.append(
                {
                    "url": url,
                    "depth": depth,
                    "error": last_error,
                    "type": "exhausted_retries",
                    "attempts": max_retries + 1,
                }
            )
        return None

    @staticmethod
    def _classify_error(error: str) -> str:
        """Classify an error as transient or permanent."""
        error_lower = error.lower()
        transient_keywords = [
            "timeout",
            "timed out",
            "connection",
            "reset",
            "refused",
            "500",
            "502",
            "503",
            "504",
            "temporarily",
            "rate limit",
            "too many requests",
            "server error",
            "network",
        ]
        for keyword in transient_keywords:
            if keyword in error_lower:
                return "transient"
        return "permanent"

    @staticmethod
    def _extract_links(html: str, base_url: str) -> list[str]:
        """Extract all valid HTTP/HTTPS links from HTML."""
        links: list[str] = []
        try:
            soup = BeautifulSoup(html, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
                    continue
                absolute = urljoin(base_url, href)
                parsed = urlparse(absolute)
                if parsed.scheme in ("http", "https"):
                    clean_url = absolute.split("#")[0]
                    if clean_url:
                        links.append(clean_url)
        except Exception:  # noqa: BLE001
            pass
        return links
