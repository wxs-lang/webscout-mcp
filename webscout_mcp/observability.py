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

import threading
from collections import defaultdict
from datetime import datetime, timezone
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

_MAX_LATENCIES = 500  # ring buffer per backend


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
        return {
            "started_at": _STARTED_AT,
            "backends": backends,
            "escalations": dict(_ESCALATION_REASONS),
            "ssrf_blocks": dict(_SSRF_BLOCKS),
            "recovery_reasons": dict(_RECOVERY_REASONS),
            "recovery_actions": dict(_RECOVERY_ACTIONS),
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
        _STARTED_AT = datetime.now(timezone.utc).isoformat()
