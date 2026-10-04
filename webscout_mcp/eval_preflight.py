"""Evaluation preflight (v1.5.0 Phase 2.1).

``run_preflight()`` reports, as structured booleans + paths + human reasons,
whether each evaluation capability can run *without* changing production
routing. The only external touch is a short, localhost reachability probe of the
configured Crawl4AI sidecar; any probe failure is treated as "unavailable" and
never raises.

GUARANTEE: this module never returns or prints a credential value, Authorization
header, token, cookie or any other secret — only presence booleans and paths.
"""

from __future__ import annotations

import os
from typing import Any

from .logging_config import get_logger

log = get_logger(__name__)


def _typesafe_sdk_importable() -> bool:
    try:
        import typesafe_sdk  # noqa: F401
    except Exception:  # noqa: BLE001 - ImportError or any side-effect error
        return False
    return True


def _credential_present(cfg: Any) -> bool:
    """Presence-only check. Never returns the credential value."""
    if os.environ.get("TYPESAFE_API_KEY"):
        return True
    return bool(getattr(cfg, "jev_api_key", ""))


def _search_provider_count(cfg: Any) -> int:
    try:
        from .search_providers import build_default_search_providers

        return len(build_default_search_providers(cfg))
    except Exception:  # noqa: BLE001 - preflight must never raise
        return 0


def _crawl4ai_reachable(base_url: str, timeout: float = 1.5) -> bool:
    """Short reachability probe of the configured sidecar.

    Isolated as a module-level function so tests can monkeypatch it. Any error
    (connect, timeout, HTTP status) means "unavailable".
    """
    if not base_url:
        return False
    try:
        import httpx

        resp = httpx.get(base_url, timeout=timeout)
        # Any HTTP response means the sidecar answered.
        return resp.status_code > 0
    except Exception:  # noqa: BLE001 - treat any failure as unavailable
        return False


def _verdict(ready: bool, reasons: list[str]) -> dict[str, Any]:
    return {"status": "READY" if ready else "BLOCKED", "reasons": reasons}


def run_preflight() -> dict[str, Any]:
    """Run all preflight checks and return a structured status dict.

    The returned dict carries only booleans, counts, paths and reason strings.
    It deliberately excludes every secret value.
    """
    from . import decision_store, jev_store
    from .config import Config
    from .crawl4ai_backend import Crawl4AIBrowserBackend

    cfg = Config.from_env()

    sdk_ok = _typesafe_sdk_importable()
    cred_ok = _credential_present(cfg)
    jev_enabled = bool(getattr(cfg, "jev_enabled", False))
    search_count = _search_provider_count(cfg)

    browser_backend = Crawl4AIBrowserBackend(cfg)
    browser_configured = bool(browser_backend.is_available)
    sidecar_reachable = False
    if browser_configured:
        sidecar_reachable = _crawl4ai_reachable(getattr(browser_backend, "base_url", ""))

    # --- Per-capability verdicts ------------------------------------------------
    fetch_reasons: list[str] = ["HTTP fetch provider available"]
    fetch_live = _verdict(True, fetch_reasons)

    if search_count > 0:
        search_live = _verdict(True, [f"{search_count} search provider(s) configured"])
    else:
        search_live = _verdict(False, ["no search provider configured"])

    jev_reasons: list[str] = []
    jev_ready = True
    if not sdk_ok:
        jev_ready = False
        jev_reasons.append("typesafe SDK not installed")
    if not cred_ok:
        jev_ready = False
        jev_reasons.append("missing TypeSafe credential")
    if jev_ready and not jev_enabled:
        jev_reasons.append("JEV_ENABLED=false; shadow wired but disabled at runtime")
    if not jev_reasons:
        jev_reasons.append("TypeSafe SDK present and credential configured")
    jev_shadow = _verdict(jev_ready, jev_reasons)

    browser_reasons: list[str] = []
    browser_ready = True
    if not browser_configured:
        browser_ready = False
        browser_reasons.append("Crawl4AI browser backend not configured (CRAWL4AI_ENABLED / BASE_URL)")
    elif not sidecar_reachable:
        browser_ready = False
        browser_reasons.append("crawl4ai sidecar unavailable")
    if browser_ready:
        browser_reasons.append("browser backend configured and sidecar reachable")
    browser_counterfactual = _verdict(browser_ready, browser_reasons)

    return {
        "checks": {
            "typesafe_sdk_importable": sdk_ok,
            "typesafe_credential_present": cred_ok,
            "jev_enabled": jev_enabled,
            "search_provider_count": search_count,
            "browser_backend_configured": browser_configured,
            "crawl4ai_sidecar_reachable": sidecar_reachable,
        },
        "paths": {
            "decision_db": str(decision_store.db_path()),
            "jev_db": str(jev_store.db_path()),
        },
        "capabilities": {
            "fetch_live": fetch_live,
            "search_live": search_live,
            "jev_shadow": jev_shadow,
            "browser_counterfactual": browser_counterfactual,
        },
    }


def to_text(report: dict[str, Any]) -> str:
    """Pretty-print a preflight report. Never emits secrets."""
    checks = report.get("checks", {})
    paths = report.get("paths", {})
    caps = report.get("capabilities", {})

    lines: list[str] = []
    lines.append("WebScout evaluation preflight")
    lines.append("=" * 32)
    lines.append("Checks:")
    for key, val in checks.items():
        lines.append(f"  - {key}: {val}")
    lines.append("Paths:")
    for key, val in paths.items():
        lines.append(f"  - {key}: {val}")
    lines.append("Capabilities:")
    for name, verdict in caps.items():
        status = verdict.get("status", "?")
        reasons = "; ".join(verdict.get("reasons", []))
        lines.append(f"  - {name}: {status}" + (f" ({reasons})" if reasons else ""))
    return "\n".join(lines)
