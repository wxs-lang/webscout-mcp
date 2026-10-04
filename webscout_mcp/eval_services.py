"""Production service bootstrap for evaluation (v1.5.0 Phase 2.1).

This module builds the *exact* production service graph that ``server.py``
constructs, but scoped to a single evaluation run:

  * a per-run directory ``.webscout-eval/<run_id>/`` holds run-local SQLite
    databases (decision events + Jev shadow records) so an evaluation run never
    touches the developer's production databases;
  * the process-wide ``PROCESS_RUN_ID`` is pinned to ``run_id`` *before* any
    service is built, including patching already-imported module bindings
    (services bind the run id by value at import, so merely setting the
    environment is insufficient);
  * the provider registry, search service, HTTP fetch provider and (optionally)
    the Crawl4AI browser backend are wired exactly as in ``server.py`` — this
    module never hand-rolls routing.

Evaluation-only: it changes no production routing, recovery decisions or MCP
tool signatures. It only *feeds* the production services and flushes their
shadow state.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from .cache import Cache
from .config import Config
from .fetcher import Fetcher
from .logging_config import get_logger

log = get_logger(__name__)

# Modules that bind ``PROCESS_RUN_ID`` by value at import time. Patching the
# environment alone is not enough; we re-point each already-imported binding.
_RUN_ID_BINDING_MODULES = (
    "webscout_mcp.fetch_service",
    "webscout_mcp.search_service",
    "webscout_mcp.jev_shadow",
)


def _pin_process_run_id(run_id: str) -> None:
    """Pin the evaluation run id across env + already-imported bindings.

    Services capture ``PROCESS_RUN_ID`` by value at import; we must re-point
    every copy (and the env vars) *before* constructing any service so that
    every DecisionEvent / Jev shadow record written during this run carries the
    evaluation ``run_id`` rather than a stale process id.
    """
    os.environ["WEBSCOUT_RUN_ID"] = run_id
    os.environ["JEV_RUN_ID"] = run_id
    try:
        from . import runtime_context

        runtime_context.PROCESS_RUN_ID = run_id
    except Exception:  # pragma: no cover - defensive
        log.debug("eval: could not patch runtime_context.PROCESS_RUN_ID", exc_info=True)
    for mod_name in _RUN_ID_BINDING_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "PROCESS_RUN_ID"):
            try:
                setattr(mod, "PROCESS_RUN_ID", run_id)  # noqa: B010
            except Exception:  # pragma: no cover - defensive
                log.debug("eval: could not patch %s.PROCESS_RUN_ID", mod_name, exc_info=True)


def configure_eval_run(run_id: str, *, base_dir: Path | None = None) -> dict[str, Any]:
    """Bootstrap production services scoped to one evaluation run.

    Args:
        run_id: Evaluation run identifier. Used for the per-run directory, the
            per-run SQLite databases and the process-wide run-id binding.
        base_dir: Optional base directory; defaults to the current working
            directory. The run directory is ``<base_dir>/.webscout-eval/<run_id>``.

    Returns:
        A dict with the live services and paths::

            {
                "fetch_service": FetchService,
                "search_service": SearchService | None,
                "registry": ProviderRegistry,
                "config": Config,
                "fetcher": Fetcher,
                "cache": Cache,
                "browser_backend": Crawl4AIBrowserBackend | None,
                "decision_db": Path,
                "jev_db": Path,
                "eval_dir": Path,
                "run_id": str,
            }
    """
    # 1) Per-run directory + per-run databases.
    root = Path(base_dir) if base_dir is not None else Path.cwd()
    eval_dir = root / ".webscout-eval" / run_id
    eval_dir.mkdir(parents=True, exist_ok=True)
    decision_db = eval_dir / "decision.db"
    jev_db = eval_dir / "jev.db"

    # 2) Pin the run id BEFORE building services (env + module bindings).
    _pin_process_run_id(run_id)
    os.environ["WEBSCOUT_DECISION_DB"] = str(decision_db)
    os.environ["WEBSCOUT_JEV_DB"] = str(jev_db)

    from . import decision_store, jev_store

    decision_store.configure(decision_db)
    jev_store.configure(jev_db)

    # 3) Build the production service graph, mirroring server.py exactly.
    cfg = Config.from_env()
    cfg.ensure_dirs()

    cache = Cache(
        db_path=cfg.cache_dir / "webscout.db",
        ttl=cfg.cache_ttl,
        max_size_mb=cfg.cache_max_size_mb,
    )
    fetcher = Fetcher(cfg, cache)

    from .crawl4ai_backend import Crawl4AIBrowserBackend
    from .fetch_provider import HTTPFetchProvider
    from .fetch_service import FetchService
    from .provider_registry import ProviderRegistry
    from .provider_router import ProviderCapability, ProviderCostTier
    from .search_service import create_search_service_from_config

    registry = ProviderRegistry()

    try:
        search_service: Any = create_search_service_from_config(cfg, cache, registry=registry)
        log.info("eval: SearchService initialized for run %s", run_id)
    except Exception as exc:  # noqa: BLE001 - mirror server.py fallback behaviour
        log.warning("eval: could not initialize SearchService: %s", exc)
        search_service = None

    try:
        registry.register(
            HTTPFetchProvider(fetcher),
            capabilities={ProviderCapability.FETCH},
            cost_tier=ProviderCostTier.FREE,
            description="HTTP fetch provider (smart Fetcher)",
        )
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("eval: could not register HTTP fetch provider: %s", exc)

    browser_backend = Crawl4AIBrowserBackend(cfg)
    if browser_backend.is_available:
        try:
            registry.register(
                browser_backend,
                capabilities={ProviderCapability.BROWSER},
                cost_tier=ProviderCostTier.PAID,
                description="Crawl4AI browser render sidecar (escalation only, BROWSER capability)",
            )
            log.info("eval: Crawl4AI sidecar registered at %s", browser_backend.base_url)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("eval: could not register Crawl4AI backend: %s", exc)
    else:
        log.info("eval: Crawl4AI sidecar not configured; fetch uses fast path only")

    fetch_service = FetchService(registry=registry, config=cfg)

    return {
        "fetch_service": fetch_service,
        "search_service": search_service,
        "registry": registry,
        "config": cfg,
        "fetcher": fetcher,
        "cache": cache,
        "browser_backend": browser_backend if browser_backend.is_available else None,
        "decision_db": decision_db,
        "jev_db": jev_db,
        "eval_dir": eval_dir,
        "run_id": run_id,
    }


async def aclose_services(services: dict[str, Any]) -> None:
    """Flush pending Jev shadow tasks and close production services.

    Best-effort: a failure closing one resource never prevents the rest from
    closing.
    """
    fetch_service = services.get("fetch_service")
    if fetch_service is not None:
        try:
            await fetch_service.flush_pending_jev_tasks()
        except Exception:  # pragma: no cover - defensive
            log.debug("eval: fetch service jev flush failed", exc_info=True)

    search_service = services.get("search_service")
    if search_service is not None:
        try:
            await search_service.close()
        except Exception:  # pragma: no cover - defensive
            log.debug("eval: search service close failed", exc_info=True)

    fetcher = services.get("fetcher")
    if fetcher is not None:
        try:
            await fetcher.close()
        except Exception:  # pragma: no cover - defensive
            log.debug("eval: fetcher close failed", exc_info=True)
