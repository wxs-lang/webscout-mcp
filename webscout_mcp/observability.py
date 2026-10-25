"""Lightweight in-process observability for webscout-mcp.

v1.2.4 adds zero external dependencies. All metrics live in memory and are
exposed through :func:`get_observability_summary`. The 7-day stability
workflow already captures logs; this module just makes the per-request
facts consistent and safe.

Privacy rules (enforced by the helpers below, not by caller discipline):

  * Never log full URLs with query strings — only scheme://host.
  * Never log Authorization / Cookie / tokens.
  * Never log resolved internal IPs on rejection — only the reason code.
"""

from __future__ import annotations

import atexit
import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .logging_config import get_logger

log = get_logger(__name__)


_LOCK = threading.Lock()
_STARTED_AT = datetime.now(timezone.utc).isoformat()


def _new_bucket() -> dict[str, Any]:
    return {
        "calls": 0,
        "success": 0,
        "failure": 0,
        "timeout": 0,
        "forbidden": 0,
        "latencies_ms": [],  # keep last N for P50/P95
    }


# backend -> bucket
_BACKEND_BUCKETS: dict[str, dict[str, Any]] = defaultdict(_new_bucket)
# reason_code -> count (escalations)
_ESCALATION_REASONS: dict[str, int] = defaultdict(int)
# reason_code -> count (SSRF blocks)
_SSRF_BLOCKS: dict[str, int] = defaultdict(int)
# recovery classification counters (Phase 2.7B): reason/action -> count
_RECOVERY_REASONS: dict[str, int] = defaultdict(int)
_RECOVERY_ACTIONS: dict[str, int] = defaultdict(int)
# recovery execution counters (Phase 2.7D): action -> outcome -> count
_RECOVERY_EXECUTION: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
# progressive content delivery counters (Phase 2.7C)
_CONTINUATION: dict[str, int] = defaultdict(int)
# Crawl lifecycle counters (Stable hardening Phase 1). Scalars only.
_CRAWL: dict[str, int] = defaultdict(int)
_CRAWL_BLOCKED: dict[str, int] = defaultdict(int)  # robots | ssrf
# Content-usability counters (GOAL G1/G4). Scalars only — never content.
_CONTENT_QUALITY: dict[str, int] = defaultdict(int)
_CONTENT_RETURNED_CHARS: list[int] = []

_MAX_LATENCIES = 500  # ring buffer per backend
_MAX_CONTENT_SAMPLES = 500  # ring buffer for returned-content sizes

# A fetched page returning fewer than this many characters is not usable as
# evidence for an agent. 200 is deliberately low: it counts navigation-only
# or captcha-only bodies as thin, while keeping short legitimate snippets
# (a one-line answer, a stock quote) out of the thin bucket.
THIN_CONTENT_CHARS = 200


def safe_host(url: str) -> str:
    """Strip a URL down to scheme://host — never path/query/credentials."""
    try:
        p = urlparse(url)
        host = p.hostname
        if not host or not p.scheme:
            return "invalid-url"
        if p.port:
            host = f"{host}:{p.port}"
        return f"{p.scheme}://{host}"
    except Exception:  # noqa: BLE001
        return "invalid-url"


def record_fetch_attempt(
    backend: str,
    *,
    result: str,
    latency_ms: float,
    reason: str | None = None,
) -> None:
    """Record one fetch attempt.

    Args:
        backend: ``fast-http``, ``crawl4ai``, ...
        result: ``success`` / ``failure`` / ``timeout`` / ``forbidden``
        latency_ms: wall time for this backend call
        reason: optional escalation/error reason code (no PII)
    """
    with _LOCK:
        b = _BACKEND_BUCKETS[backend]
        b["calls"] += 1
        if result in ("success", "failure", "timeout", "forbidden"):
            b[result] += 1
        b["latencies_ms"].append(round(latency_ms, 2))
        if len(b["latencies_ms"]) > _MAX_LATENCIES:
            b["latencies_ms"] = b["latencies_ms"][-_MAX_LATENCIES:]

    # Structured log line — host only, no query string.
    log.info(
        "fetch_attempt",
        extra={
            "backend": backend,
            "result": result,
            "latency_ms": round(latency_ms, 2),
            "reason": reason,
        },
    )


def record_escalation(reason_code: str) -> None:
    with _LOCK:
        _ESCALATION_REASONS[reason_code] += 1
    log.info("fetch_escalation", extra={"reason_code": reason_code})


def record_ssrf_block(reason_code: str) -> None:
    with _LOCK:
        _SSRF_BLOCKS[reason_code] += 1
    log.info("ssrf_block", extra={"reason_code": reason_code})


def record_recovery_classification(reason_code: str, action: str) -> None:
    """Count a deterministic recovery classification (Phase 2.7B).

    Classification only — this never executes the recommended action.
    """
    with _LOCK:
        _RECOVERY_REASONS[reason_code] += 1
        _RECOVERY_ACTIONS[action] += 1


def record_recovery_execution(action: str, outcome: str) -> None:
    """Count the executed outcome of one recovery orchestration (Phase 2.7D).

    One call per primary fetch orchestration; only scalar action/outcome
    pairs are kept — never content, URLs, headers, or credentials.
    """
    with _LOCK:
        _RECOVERY_EXECUTION[action][outcome] += 1


def record_continuation(kind: str, chars: int = 0) -> None:
    """Count progressive-content-delivery events (Phase 2.7C).

    kind is one of: request, snapshot_hit, snapshot_miss, snapshot_rebuild,
    chunk_served. ``chars`` accumulates delivered window chars. Only scalar
    counts are kept — never content, URLs, headers, or credentials.
    """
    with _LOCK:
        _CONTINUATION[kind] += 1
        if chars:
            _CONTINUATION["chars_served"] += int(chars)


def record_crawl_lifecycle(
    status: str,
    *,
    seed: str = "",
    pages: int = 0,
    duration_ms: float = 0.0,
) -> None:
    """Count a crawl lifecycle event.

    status is one of: started, success, partial, failure. Only the seed
    HOST (scheme://host, no path/query) is logged — never credentials.
    """
    with _LOCK:
        key = f"crawl_{status}"
        _CRAWL[key] += 1
        if pages:
            _CRAWL["crawl_pages_total"] += int(pages)
    log.info(
        "crawl_lifecycle",
        extra={"status": status, "seed": seed, "pages": pages, "duration_ms": round(duration_ms, 2)},
    )


def record_crawl_blocked(kind: str) -> None:
    """Count a per-page block. kind is 'robots' or 'ssrf'."""
    with _LOCK:
        _CRAWL_BLOCKED[kind] += 1
    log.info("crawl_blocked", extra={"kind": kind})


def record_content_quality(
    *,
    returned_chars: int,
    pre_limit_chars: int | None = None,
    truncated: bool = False,
    omitted_chars: int = 0,
    backend: str = "",
    status: str = "",
) -> None:
    """Record the usability of one served fetch result (GOAL G1/G4).

    This is the instrument that makes "did we actually get usable content?"
    observable. Before it existed, the counters in this module could only say
    "the request did not error" — a 200 response whose body was a captcha or a
    navigation shell counted as a success. The v1.9.0 A/B run measured a
    7.3pp content-usability gap against a bare baseline while every success
    metric stayed green; this counter is what would have caught it.

    Every argument is a scalar. Content, URLs, headers and credentials are
    never accepted here, so they can never leak through this path.
    """
    chars = max(0, int(returned_chars or 0))
    with _LOCK:
        _CONTENT_QUALITY["fetches"] += 1
        if status:
            _CONTENT_QUALITY[f"status_{status}"] += 1
        if backend:
            _CONTENT_QUALITY[f"backend_{backend}"] += 1

        if chars == 0:
            _CONTENT_QUALITY["empty"] += 1
        elif chars < THIN_CONTENT_CHARS:
            _CONTENT_QUALITY["thin"] += 1
        else:
            _CONTENT_QUALITY["usable"] += 1

        if truncated:
            _CONTENT_QUALITY["truncated_by_output_limit"] += 1
        _CONTENT_QUALITY["chars_returned_total"] += chars
        if pre_limit_chars is not None:
            _CONTENT_QUALITY["pre_limit_chars_total"] += max(0, int(pre_limit_chars))
        if omitted_chars:
            _CONTENT_QUALITY["chars_omitted_total"] += max(0, int(omitted_chars))

        _CONTENT_RETURNED_CHARS.append(chars)
        if len(_CONTENT_RETURNED_CHARS) > _MAX_CONTENT_SAMPLES:
            del _CONTENT_RETURNED_CHARS[:-_MAX_CONTENT_SAMPLES]

    log.info(
        "content_quality",
        extra={
            "returned_chars": chars,
            "pre_limit_chars": pre_limit_chars,
            "truncated_by_output_limit": bool(truncated),
            "omitted_chars": omitted_chars,
            "backend": backend,
            "status": status,
        },
    )


def _rate(numerator: int, denominator: int) -> float:
    """Ratio in [0,1]; 0.0 when there is nothing to divide by."""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(p * (len(s) - 1))))
    return s[k]


def get_observability_summary() -> dict[str, Any]:
    """Return a JSON-serialisable snapshot. Safe to call at any time."""
    with _LOCK:
        backends: dict[str, Any] = {}
        for name, b in _BACKEND_BUCKETS.items():
            lat = list(b["latencies_ms"])
            backends[name] = {
                "calls": b["calls"],
                "success": b["success"],
                "failure": b["failure"],
                "timeout": b["timeout"],
                "forbidden": b["forbidden"],
                "p50_ms": round(_pct(lat, 0.50), 2),
                "p95_ms": round(_pct(lat, 0.95), 2),
                "samples": len(lat),
            }
        cq = dict(_CONTENT_QUALITY)
        fetches = cq.get("fetches", 0)
        returned = list(_CONTENT_RETURNED_CHARS)
        content_quality = {
            "fetches": fetches,
            "usable": cq.get("usable", 0),
            "thin": cq.get("thin", 0),
            "empty": cq.get("empty", 0),
            "usable_rate": _rate(cq.get("usable", 0), fetches),
            "thin_rate": _rate(cq.get("thin", 0), fetches),
            "empty_rate": _rate(cq.get("empty", 0), fetches),
            "truncated_by_output_limit": cq.get("truncated_by_output_limit", 0),
            "truncation_rate": _rate(cq.get("truncated_by_output_limit", 0), fetches),
            "thin_threshold_chars": THIN_CONTENT_CHARS,
            "chars_returned_total": cq.get("chars_returned_total", 0),
            "chars_omitted_total": cq.get("chars_omitted_total", 0),
            "returned_p50": int(_pct([float(x) for x in returned], 0.50)),
            "returned_p95": int(_pct([float(x) for x in returned], 0.95)),
            "samples": len(returned),
            "by_status": {k[len("status_") :]: v for k, v in cq.items() if k.startswith("status_")},
            "by_backend": {k[len("backend_") :]: v for k, v in cq.items() if k.startswith("backend_")},
        }
        return {
            # timestamp is what the SLO aggregator filters on to build the 7d/30d
            # rolling windows. Without it every snapshot lands in the legacy
            # bucket and is counted in every window forever, so the windows are
            # not windows at all. Mirrors LiveTestReport.timestamp (epoch
            # seconds), which the aggregator already parses.
            "timestamp": datetime.now(timezone.utc).timestamp(),
            "started_at": _STARTED_AT,
            "backends": backends,
            "escalations": dict(_ESCALATION_REASONS),
            "ssrf_blocks": dict(_SSRF_BLOCKS),
            "recovery_reasons": dict(_RECOVERY_REASONS),
            "recovery_actions": dict(_RECOVERY_ACTIONS),
            "recovery_execution": {a: dict(o) for a, o in _RECOVERY_EXECUTION.items()},
            "continuation": dict(_CONTINUATION),
            "crawl": dict(_CRAWL),
            "crawl_blocked": dict(_CRAWL_BLOCKED),
            "content_quality": content_quality,
        }


def reset_for_tests() -> None:
    """Clear all in-memory counters. Test-only."""
    global _STARTED_AT
    with _LOCK:
        _BACKEND_BUCKETS.clear()
        _ESCALATION_REASONS.clear()
        _SSRF_BLOCKS.clear()
        _RECOVERY_REASONS.clear()
        _RECOVERY_ACTIONS.clear()
        _RECOVERY_EXECUTION.clear()
        _CONTINUATION.clear()
        _CRAWL.clear()
        _CRAWL_BLOCKED.clear()
        _CONTENT_QUALITY.clear()
        _CONTENT_RETURNED_CHARS.clear()
        _STARTED_AT = datetime.now(timezone.utc).isoformat()


def write_snapshot(path: str | Path) -> dict[str, Any]:
    """Persist the current counters to ``path`` as JSON and return the snapshot.

    Counters live in process memory, so without this they vanish on exit and
    nothing outside the process can read them. The SLO aggregator reads
    ``live_report.json`` files from disk, so a run has to leave one behind for
    its numbers to reach a report at all.

    The write is atomic (temp file + replace) so a crash mid-write cannot leave
    a truncated JSON file for the aggregator to choke on. Telemetry must never
    break the caller: failures are logged at debug level and swallowed.
    """
    snapshot = get_observability_summary()
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except Exception:  # pragma: no cover - disk problems must never break a run
        log.debug("observability snapshot write failed", exc_info=True)
    return snapshot


def read_snapshot(path: str | Path) -> dict[str, Any] | None:
    """Load a snapshot previously written by :func:`write_snapshot`.

    Returns None when the file is absent or unreadable/corrupt, so a damaged
    snapshot degrades to "no data" instead of raising in a reporting path.
    """
    try:
        target = Path(path)
        if not target.exists():
            return None
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # pragma: no cover - reporting must tolerate bad input
        log.debug("observability snapshot read failed", exc_info=True)
        return None


def has_data() -> bool:
    """True when at least one counter has recorded something worth persisting."""
    with _LOCK:
        if _CONTENT_QUALITY.get("fetches", 0) > 0:
            return True
        if any(b["calls"] for b in _BACKEND_BUCKETS.values()):
            return True
        if _ESCALATION_REASONS or _SSRF_BLOCKS or _RECOVERY_REASONS or _CRAWL:
            return True
        return bool(_CONTINUATION)


# Guards against double registration of the exit hook.
_exit_hook_registered = False


def enable_snapshot_on_exit(path: str | Path) -> None:
    """Persist a snapshot when the process exits.

    Opt-in on purpose. Library use and the test suite must not litter the
    filesystem with a snapshot for every short-lived process, so nothing is
    written unless this was called explicitly — the MCP server does, and CI
    calls it directly.

    Runs that recorded nothing are skipped entirely: a process that served no
    requests produces no file, rather than an all-zeroes snapshot that the
    aggregator would read as "measured, 0% usable content".

    Registration is idempotent; the first path wins. The write is wrapped so a
    read-only or full disk can never turn a clean process exit into a failure.
    """
    global _exit_hook_registered

    if _exit_hook_registered:
        return

    target = Path(path)

    def _flush_at_exit() -> None:
        try:
            if not has_data():
                log.debug("observability snapshot skipped: no data recorded")
                return
            write_snapshot(target)
        except Exception:  # pragma: no cover - never fail process exit
            log.debug("observability snapshot on exit failed", exc_info=True)

    atexit.register(_flush_at_exit)
    _exit_hook_registered = True


def snapshot_on_exit_enabled() -> bool:
    """True when :func:`enable_snapshot_on_exit` has been called."""
    return _exit_hook_registered
