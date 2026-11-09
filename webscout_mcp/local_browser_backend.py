"""Bring the local browser capability online without a sidecar.

## The situation

Three pieces exist and none connect:

    pyproject.toml[browser]  declares playwright>=1.40.0
    browser_fetcher.py       implements BrowserFetcher with fetch/is_available/close
    provider_registry        has no BROWSER implementation except Crawl4AI

BrowserFetcher is dead code, and it cannot work as written: it uses
playwright.sync_api, which refuses to run inside an asyncio loop -

    It looks like you are using Playwright Sync API inside the asyncio loop.

So the only wired browser path is a crawl4ai sidecar that needs Docker. Measured
consequence: 8/16 real-world sites usable.

## The fix that does not require rewriting twenty methods

The sync restriction is about the loop *thread*. A worker thread has no running
loop, so running the existing implementation via run_in_executor works - verified
against reddit, amazon and example.com, where amazon went from a 2167-char bot
page to 4087 chars of real content.

Playwright binds state to its creating thread, so the executor must be
single-worker and the fetcher created inside it.

## Availability

`is_available` must be honest: playwright being importable says nothing about the
browser binary, and `playwright install` is a separate step users miss. The first
launch failure marks the backend unavailable so a missing binary costs one attempt
rather than one per request.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .browser_fetcher import BrowserConfig, BrowserFetcher
from .fetch_provider import BrowserFetchProvider, FetchRequest, FetchResponse

log = logging.getLogger(__name__)

_MISSING_BROWSER_MARKERS = (
    "executable doesn't exist",
    "please run the following command",
    "playwright install",
    "executable does not exist",
)


class LocalBrowserBackend(BrowserFetchProvider):
    """Browser capability backed by the locally installed playwright.

    Use when no sidecar is configured. Requires both the `[browser]` extra and a
    completed `playwright install`.
    """

    name = "local-browser"

    def __init__(self, config: BrowserConfig | None = None) -> None:
        super().__init__()
        self._config = config or BrowserConfig(headless=True, timeout=45000, navigation_timeout=45000)
        # Single worker: playwright's sync API binds its state to the creating
        # thread, so every call must land on the same one.
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ws-browser")
        self._fetcher: BrowserFetcher | None = None
        self._unavailable_reason: str | None = None
        self._closed = False

    # --- availability --------------------------------------------------

    def is_configured(self) -> bool:
        """Whether the optional dependency is installed at all."""
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    def _browser_binary_present(self) -> bool:
        """Launch once and see. This is the only honest availability test.

        Checking `p.chromium.executable_path` is wrong: it reports the full
        chromium build, while a headless launch uses the headless-shell build.
        On a machine with only headless-shell installed the path check says
        missing and the browser works anyway - a false negative that would keep
        escalation switched off.

        Costs a second or two, so the answer is cached in _unavailable_reason.
        """
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                browser.close()
            return True
        except Exception:  # noqa: BLE001 - any failure means "cannot launch"
            return False

    async def probe_reachable(self) -> bool:
        """Launch a browser once to prove it works. Cached via _unavailable_reason."""
        if self._unavailable_reason is not None:
            return False
        if not self.is_configured():
            return False
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(self._executor, self._browser_binary_present)
        if not ok:
            self._unavailable_reason = "browser cannot launch; run `playwright install chromium`"
        return ok

    @property
    def is_available(self) -> bool:
        """Cheap check for synchronous wiring.

        True when playwright is importable and no launch has failed yet. The
        first real fetch settles it: a launch failure sets _unavailable_reason,
        after which escalation is skipped instead of paying a timeout per call.
        """
        return self.is_configured() and self._unavailable_reason is None

    # --- fetch ---------------------------------------------------------

    def _fetch_sync(self, url: str) -> Any:
        if self._fetcher is None:
            self._fetcher = BrowserFetcher(self._config)
        return self._fetcher.fetch(url)

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        url = str(request.url)
        if self._unavailable_reason is not None:
            return self._failure(url, self._unavailable_reason)

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(self._executor, self._fetch_sync, url)
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            if any(marker in message.lower() for marker in _MISSING_BROWSER_MARKERS):
                self._unavailable_reason = "browser binary missing; run `playwright install chromium`"
                log.warning("local browser unavailable: %s", self._unavailable_reason)
            return self._failure(url, message)

        if getattr(result, "error", None):
            message = str(result.error)
            if any(marker in message.lower() for marker in _MISSING_BROWSER_MARKERS):
                self._unavailable_reason = "browser binary missing; run `playwright install chromium`"
            return self._failure(url, message)

        content = getattr(result, "content", "") or ""
        return FetchResponse(
            url=url,
            final_url=getattr(result, "url", url) or url,
            status_code=getattr(result, "status_code", 0) or 200,
            provider=self.name,
            title=getattr(result, "title", "") or "",
            content=content,
            content_type="text/html",
            extracted=bool(content),
            extraction_status="ok" if content else "empty",
            raw_html=getattr(result, "html", "") or "",
            metadata={"backend": "local-playwright"},
        )

    @staticmethod
    def _failure(url: str, message: str) -> FetchResponse:
        return FetchResponse(
            url=url,
            final_url=url,
            status_code=0,
            provider="local-browser",
            error=message,
            metadata={"backend": "local-playwright"},
        )

    # --- lifecycle -----------------------------------------------------

    async def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "configured": self.is_configured(),
            "available": self.is_available,
            "reason": self._unavailable_reason,
        }

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        loop = asyncio.get_running_loop()

        def _shutdown() -> None:
            if self._fetcher is not None:
                try:
                    self._fetcher.close()
                except Exception:  # noqa: BLE001
                    pass
                self._fetcher = None

        try:
            await loop.run_in_executor(self._executor, _shutdown)
        finally:
            self._executor.shutdown(wait=False)
