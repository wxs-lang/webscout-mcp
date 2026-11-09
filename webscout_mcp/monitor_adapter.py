"""Adapt the async fetch pipeline to the monitor's synchronous fetcher protocol.

`WebMonitor` expects::

    fetch(url) -> object with .content and .html

`fetch_service.fetch()` is a coroutine returning a route whose primary response has
``.content`` and ``.raw_html``. This adapter bridges both differences so monitoring
benefits from TLS impersonation, browser escalation and recovery classification instead
of a bare HTTP request.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

__all__ = ["FetchServiceAdapter", "MonitorFetchResult"]


@dataclass
class MonitorFetchResult:
    """The shape `WebMonitor._get_content` reads."""

    content: str
    html: str
    status_code: int = 0
    recovery_outcome: str = ""


class FetchServiceAdapter:
    """Present an async ``fetch_service`` as the synchronous callable the monitor wants.

    Args:
        service: An object with ``async fetch(FetchRequest)``, typically the
            ``fetch_service`` that ``server.py`` builds.
        max_chars: Cap on the raw HTML size requested.
    """

    def __init__(self, service, max_chars: int = 2_000_000) -> None:
        self._service = service
        self._max_chars = max_chars
        self.last_recovery_outcome: str = ""
        self.last_error: str = ""

    def fetch(self, url: str, **kwargs) -> MonitorFetchResult:
        """Fetch one URL synchronously.

        The monitor calls this from a worker thread, so a fresh event loop is safe and
        keeps the sync/async boundary in exactly one place. If a loop is already running
        on this thread (which should not happen given how the tool dispatches), fall back
        to an empty result rather than raising into the monitor's error handling.
        """
        from .fetch_provider import FetchRequest

        request = FetchRequest(
            url=url,
            extract=False,
            output_format="html",
            max_chars=self._max_chars,
            # Monitoring must see the current body. With the cache enabled a changed page
            # keeps comparing equal to its own cached copy, so no change is ever reported.
            bypass_cache=True,
        )
        try:
            try:
                asyncio.get_running_loop()
                running = True
            except RuntimeError:
                running = False

            if running:
                # Cannot block on a coroutine from inside a live loop. Returning empty
                # silently would look like a successful fetch of an empty page, and the
                # monitor would record that as the new baseline - losing the real content
                # without any error. Record the reason so a caller can tell the two apart.
                self.last_error = (
                    "FetchServiceAdapter.fetch() was called from inside a running event "
                    "loop; dispatch it to a worker thread (asyncio.to_thread) instead."
                )
                return MonitorFetchResult(content="", html="")

            route = asyncio.run(self._service.fetch(request))
        except Exception as exc:
            # The monitor treats empty content as "nothing fetched" and skips the check;
            # raising would abort the whole monitoring run. Record why so the caller is
            # not left guessing whether the page was empty or the fetch failed.
            self.last_error = f"{type(exc).__name__}: {exc}"
            return MonitorFetchResult(content="", html="")

        self.last_error = ""
        response = getattr(route, "primary_response", None)
        content = (getattr(response, "content", "") or "") if response is not None else ""
        # `raw_html`, not `.html` - the response object has no `html` attribute. Falling
        # back to `content` matters because `_get_content` treats empty html as failure.
        html = (getattr(response, "raw_html", "") or content) if response is not None else ""
        outcome = getattr(route, "recovery_outcome", "") or ""
        self.last_recovery_outcome = outcome

        return MonitorFetchResult(
            content=content,
            html=html,
            status_code=(getattr(response, "status_code", 0) or 0) if response is not None else 0,
            recovery_outcome=outcome,
        )
