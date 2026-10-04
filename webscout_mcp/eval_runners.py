"""Hermetic corpus DRIVERS for evaluation (v1.5.0 Phase 2.1).

These drivers deliberately *only* feed inputs into the production
``FetchService`` / ``SearchService`` and flush their shadow state. They never
construct reason/action/decision/response objects: the DecisionEvent is created
by the production service itself.

Human-pack result lists are returned so a downstream human-pack builder can see
exactly what each production call produced (including the production
``trace_id``, which is generated inside the service and re-correlated here
*read-only* from the recorded DecisionEvent).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from .decision_event import canonical_url_hash, query_hash
from .fetch_provider import FetchRequest
from .logging_config import get_logger
from .search_provider import SearchRequest

log = get_logger(__name__)

# Corpus locations. Kept as module-level constants so hermetic tests can point
# them at a tmp fixture without touching the on-disk corpus.
_FETCH_CORPUS_PATH = Path(__file__).resolve().parent.parent / "scripts" / "eval_corpus" / "fetch_urls.json"
_SEARCH_CORPUS_PATH = Path(__file__).resolve().parent.parent / "scripts" / "eval_corpus" / "search_queries.json"

# Default curated subset size for the browser counterfactual sweep.
DEFAULT_BROWSER_CF_CASES = 24
_MAX_EXCERPT_CHARS = 2000


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _drain_jev_tasks(service: Any, timeout: float = 15.0) -> Any:
    """Return a coroutine that drains in-flight Jev shadow tasks on a service.

    Production ``FetchService.flush_pending_jev_tasks`` / ``SearchService.close``
    both drain ``_pending_jev_tasks`` this way; we mirror the drain without
    closing providers mid-corpus. Never raises.
    """

    async def _drain() -> None:
        tasks = getattr(service, "_pending_jev_tasks", None)
        if not tasks:
            return
        try:
            await asyncio.wait_for(
                asyncio.gather(*list(tasks), return_exceptions=True),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001 - best effort
            pass
        try:
            tasks.clear()
        except Exception:  # pragma: no cover - defensive
            pass

    return _drain()


def _latest_trace_id(
    domain: str,
    run_id: str,
    *,
    url: str | None = None,
    query: str | None = None,
) -> str:
    """Read-only correlation: find the production trace_id for this call.

    ``FetchService`` / ``SearchService`` generate the trace id internally and
    stamp it on the DecisionEvent; the route result does not carry it. We
    correlate by ``run_id`` + the privacy hash of the URL/query that the
    production adapter itself stored, then fall back to the most recent event
    for this run/domain. Never constructs or mutates anything.
    """
    from . import decision_store

    try:
        events = decision_store.load_events(domain=domain, limit=200)
    except Exception:  # pragma: no cover - defensive
        return ""

    target_hash: str | None = None
    if url is not None:
        target_hash = canonical_url_hash(url)
    elif query is not None:
        target_hash = query_hash(query)

    for ev in events:
        if ev.get("run_id") != run_id:
            continue
        feats = ev.get("request_features") or {}
        if target_hash is not None:
            if url is not None:
                if (feats.get("url") or {}).get("canonical_hash") == target_hash:
                    return ev.get("trace_id") or ""
            elif feats.get("query_hash") == target_hash:
                return ev.get("trace_id") or ""
        else:
            return ev.get("trace_id") or ""
    return ""


async def _guarded(coro: Any, timeout: float) -> tuple[Any | None, str | None]:
    """Await a coroutine with a hard timeout; return (result, error)."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout), None
    except asyncio.TimeoutError:
        return None, "timeout"
    except Exception as exc:  # noqa: BLE001 - record natural failures, never raise
        return None, f"{type(exc).__name__}: {exc}"


async def run_fetch_corpus(
    fetch_service: Any,
    run_id: str,
    *,
    limit: int = 0,
    per_request_timeout: float = 30.0,
) -> dict[str, Any]:
    """Drive the production fetch corpus through ``FetchService.fetch``.

    The driver only feeds ``FetchRequest`` objects and flushes shadow state.
    It never builds decisions. Returns counts plus a human-pack result list.
    """
    data = _load_json(_FETCH_CORPUS_PATH)
    entries = list(data.get("urls", []))
    if limit and limit > 0:
        entries = entries[:limit]

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0

    for entry in entries:
        url = entry["url"]
        request = FetchRequest(
            url=url,
            extract=True,
            output_format="markdown",
            max_chars=8000,
            bypass_cache=True,
        )
        route, err = await _guarded(fetch_service.fetch(request), per_request_timeout)

        if route is None:
            failed += 1
            results.append(
                {
                    "url": url,
                    "trace_id": _latest_trace_id("fetch", run_id, url=url),
                    "status": "error",
                    "status_code": 0,
                    "chars": 0,
                    "title": "",
                    "excerpt": "",
                    "error": err or "failed",
                }
            )
            continue

        primary = route.primary_response
        final = route.final_response
        content = final.content or primary.content or ""
        chars = len(content) if isinstance(content, str) else 0
        title = final.title or primary.title or ""
        if getattr(route, "browser_success", False):
            status = "browser_success"
        elif primary.is_success:
            status = "success"
        else:
            status = "error"
            failed += 1
        if status != "error":
            succeeded += 1

        results.append(
            {
                "url": url,
                "trace_id": _latest_trace_id("fetch", run_id, url=url),
                "status": status,
                "status_code": int(primary.status_code or 0),
                "chars": chars,
                "title": title,
                "excerpt": content[:_MAX_EXCERPT_CHARS] if isinstance(content, str) else "",
            }
        )

    await _drain_jev_tasks(fetch_service)

    return {
        "run_id": run_id,
        "total": len(entries),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


async def run_search_corpus(
    search_service: Any,
    run_id: str,
    *,
    limit: int = 0,
    per_request_timeout: float = 30.0,
) -> dict[str, Any]:
    """Drive the production search corpus through ``SearchService.search``.

    The driver only feeds ``SearchRequest`` objects and flushes shadow state.
    It never builds a SearchResponse. Targets ~>=100 result rows across the
    43-query corpus.
    """
    data = _load_json(_SEARCH_CORPUS_PATH)
    entries = list(data.get("queries", []))
    if limit and limit > 0:
        entries = entries[:limit]

    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    total_rows = 0

    for entry in entries:
        query = entry["query"]
        request = SearchRequest(
            query=query,
            max_results=10,
            region="wt-wt",
            safe_search=True,
        )
        response, err = await _guarded(search_service.search(request), per_request_timeout)

        if response is None:
            failed += 1
            results.append(
                {
                    "query": query,
                    "trace_id": _latest_trace_id("search", run_id, query=query),
                    "rows": [],
                    "status": "error",
                    "error": err or "failed",
                }
            )
            continue

        rows = [
            {
                "position": int(getattr(r, "position", i + 1) or 0),
                "title": getattr(r, "title", "") or "",
                "snippet": getattr(r, "snippet", "") or "",
                "url": getattr(r, "url", "") or "",
            }
            for i, r in enumerate(getattr(response, "results", []) or [])
        ]
        total_rows += len(rows)
        status_val = getattr(getattr(response, "status", None), "value", "success")
        if getattr(response, "is_success", False):
            succeeded += 1
        else:
            failed += 1

        results.append(
            {
                "query": query,
                "trace_id": _latest_trace_id("search", run_id, query=query),
                "rows": rows,
                "status": status_val,
            }
        )

    await _drain_jev_tasks(search_service)

    return {
        "run_id": run_id,
        "total": len(entries),
        "succeeded": succeeded,
        "failed": failed,
        "result_rows": total_rows,
        "results": results,
    }


async def run_browser_counterfactual(
    services: dict[str, Any],
    run_id: str,
    *,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """Evaluation-only: compare FAST vs BROWSER for a curated fetch subset.

    For each URL we:
      1. run the *production* fetch path once (so the production DecisionEvent
         + trace_id exists for correlation), then
      2. independently call the HTTP fetch provider and the Crawl4AI browser
         backend directly, WITHOUT going through recovery, and record the raw
         facts.

    We deliberately do NOT infer "browser_required" from a positive char gain:
    this writes raw facts only. Output is a JSONL artifact in the run dir.
    """
    fetch_service = services.get("fetch_service")
    registry = services.get("registry")
    eval_dir = Path(services.get("eval_dir") or ".webscout-eval")
    if fetch_service is None or registry is None:
        log.warning("browser counterfactual: fetch_service/registry not available")
        return []

    http_provider = registry.get("http")
    browser_backend = registry.get("crawl4ai")
    if http_provider is None or browser_backend is None:
        log.warning("browser counterfactual: http or crawl4ai provider not registered; skipping")
        return []

    data = _load_json(_FETCH_CORPUS_PATH)
    entries = list(data.get("urls", []))
    n = limit if (limit and limit > 0) else DEFAULT_BROWSER_CF_CASES
    entries = entries[:n]

    artifact_path = eval_dir / "browser-counterfactual.jsonl"
    eval_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    with artifact_path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            url = entry["url"]
            request = FetchRequest(
                url=url,
                extract=True,
                output_format="markdown",
                max_chars=8000,
                bypass_cache=True,
            )

            # (1) Production path — mints the authoritative trace_id.
            route, _ = await _guarded(fetch_service.fetch(request), 30.0)
            source_trace = _latest_trace_id("fetch", run_id, url=url)
            if not source_trace and route is not None:
                # Best effort: correlation may lag; leave blank rather than fabricate.
                source_trace = ""

            # (2) Independent direct backends — no recovery, no routing.
            primary, _ = await _guarded(http_provider.fetch(request), 30.0)
            browser, _ = await _guarded(browser_backend.fetch(request), 60.0)

            primary_chars = len(primary.content or "") if primary is not None else 0
            browser_chars = len(browser.content or "") if browser is not None else 0

            case = {
                "case_id": f"cf:{uuid.uuid4().hex}",
                "run_id": run_id,
                "source_trace_id": source_trace,
                "url": url,
                "primary_status": "success" if (primary is not None and primary.is_success) else "error",
                "browser_status": "success" if (browser is not None and browser.is_success) else "error",
                "primary_chars": primary_chars,
                "browser_chars": browser_chars,
                "gain": browser_chars - primary_chars,
                "primary_extraction_success": bool(primary is not None and primary.is_success and primary.extracted),
                "browser_extraction_success": bool(browser is not None and browser.is_success and browser.extracted),
            }
            cases.append(case)
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")

    await _drain_jev_tasks(fetch_service)
    return cases
