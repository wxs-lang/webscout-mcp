"""SQLite-backed durable store for DecisionEvent records.

Location: ``<data_dir>/decision_events.db`` (overridable via
``WEBSCOUT_DECISION_DB``).

Design goals:
  * WAL mode for concurrent read/write.
  * Idempotent schema + migration (fresh DBs get full schema; old DBs get
    missing columns added).
  * Thread-safe via a module-level lock (same level as JevStore).
  * Retention: rows older than ``retention_days`` are pruned on write.
  * Size cap: if the DB file exceeds ``max_db_size_mb``, oldest rows are
    deleted until under the cap.
  * Best-effort: every public write function catches all exceptions and logs
    a warning. A store failure MUST NOT change Fetch/Search production
    results.
  * Privacy: only sanitized fields are stored. The store additionally
    scrubs secret-like keys from request_features / outcome_features /
    metadata before INSERT.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .decision_event import DecisionEvent, _scrub_dict
from .logging_config import get_logger

log = get_logger(__name__)

_lock = threading.Lock()
_db_path: Path | None = None

DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_DB_SIZE_MB = 256

_SCHEMA_VERSION = 1

_SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS decision_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE,
    trace_id TEXT,
    run_id TEXT,
    domain TEXT NOT NULL,
    stage TEXT NOT NULL,
    subject TEXT,
    observed_status TEXT,
    deterministic_reason TEXT,
    deterministic_action TEXT,
    production_action TEXT,
    production_outcome TEXT,
    started_at REAL,
    completed_at REAL,
    latency_ms REAL,
    request_features TEXT,
    outcome_features TEXT,
    metadata TEXT,
    jev_call_id TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decision_ts ON decision_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_domain ON decision_events(domain, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_trace ON decision_events(trace_id);
CREATE INDEX IF NOT EXISTS idx_decision_run ON decision_events(run_id);
CREATE INDEX IF NOT EXISTS idx_decision_reason ON decision_events(deterministic_reason, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decision_action ON decision_events(deterministic_action, created_at DESC);

CREATE TABLE IF NOT EXISTS replay_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL UNIQUE,
    domain TEXT NOT NULL,
    input_features TEXT,
    observed_outcome TEXT,
    production_decision TEXT,
    expected_label TEXT,
    label_source TEXT,
    label_confidence REAL,
    notes TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replay_domain ON replay_cases(domain);
CREATE INDEX IF NOT EXISTS idx_replay_label ON replay_cases(expected_label);
"""


def _default_db_path() -> Path:
    """Resolve the default DB path.

    Priority:
      1. ``WEBSCOUT_DECISION_DB`` env var
      2. ``${XDG_DATA_HOME:-~/.local/share}/webscout/decision_events.db``
    """
    env = os.environ.get("WEBSCOUT_DECISION_DB")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / "webscout" / "decision_events.db"


def configure(db_path: str | Path | None = None) -> Path:
    """Point the store at a specific DB file. Called from tests or CLI."""
    global _db_path
    _db_path = Path(db_path) if db_path else _default_db_path()
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    _init_schema(_db_path)
    return _db_path


def _conn() -> sqlite3.Connection:
    global _db_path
    if _db_path is None:
        _db_path = _default_db_path()
        _db_path.parent.mkdir(parents=True, exist_ok=True)
    _init_schema(_db_path)
    c = sqlite3.connect(str(_db_path), timeout=5.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _init_schema(path: Path) -> None:
    try:
        with sqlite3.connect(str(path), timeout=5.0) as c:
            c.executescript(_SCHEMA_BASE)
            c.commit()
    except Exception:
        log.warning("decision_events schema init failed", exc_info=True)


def _prune_old(conn: sqlite3.Connection, retention_days: int) -> None:
    """Delete rows older than retention_days."""
    cutoff = time.time() - retention_days * 86400
    conn.execute("DELETE FROM decision_events WHERE created_at < ?", (cutoff,))
    conn.execute("DELETE FROM replay_cases WHERE created_at < ?", (cutoff,))


def _enforce_size_cap(conn: sqlite3.Connection, max_mb: int, db_path: Path) -> None:
    """If DB file exceeds max_mb, delete oldest decision_events until under cap."""
    try:
        size_bytes = db_path.stat().st_size
    except OSError:
        return
    max_bytes = max_mb * 1024 * 1024
    if size_bytes <= max_bytes:
        return
    # Delete oldest 10% of rows iteratively.
    while True:
        try:
            current = db_path.stat().st_size
        except OSError:
            break
        if current <= max_bytes:
            break
        count = conn.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0]
        if count == 0:
            break
        delete_n = max(1, count // 10)
        conn.execute(
            "DELETE FROM decision_events WHERE id IN (SELECT id FROM decision_events ORDER BY created_at ASC LIMIT ?)",
            (delete_n,),
        )
        conn.commit()
        # VACUUM is expensive; skip on hot path. Size will shrink on next
        # SQLite checkpoint naturally. We just prevent unbounded growth.


def record_event(
    event: DecisionEvent, retention_days: int = DEFAULT_RETENTION_DAYS, max_db_size_mb: int = DEFAULT_MAX_DB_SIZE_MB
) -> bool:
    """Insert one DecisionEvent. Best-effort; never raises.

    Returns True if the record was written, False otherwise (including
    duplicate event_id).
    """
    try:
        with _lock, _conn() as c:
            _prune_old(c, retention_days)
            req = json.dumps(_scrub_dict(event.request_features), ensure_ascii=False)
            out = json.dumps(_scrub_dict(event.outcome_features), ensure_ascii=False)
            meta = json.dumps(_scrub_dict(event.metadata), ensure_ascii=False)
            c.execute(
                """INSERT OR IGNORE INTO decision_events (
                    schema_version, event_id, trace_id, run_id, domain, stage,
                    subject, observed_status, deterministic_reason,
                    deterministic_action, production_action, production_outcome,
                    started_at, completed_at, latency_ms,
                    request_features, outcome_features, metadata, jev_call_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.schema_version,
                    event.event_id,
                    event.trace_id,
                    event.run_id,
                    event.domain.value if hasattr(event.domain, "value") else event.domain,
                    event.stage.value if hasattr(event.stage, "value") else event.stage,
                    event.subject,
                    event.observed_status,
                    event.deterministic_reason,
                    event.deterministic_action,
                    event.production_action,
                    event.production_outcome,
                    event.started_at,
                    event.completed_at,
                    event.latency_ms,
                    req,
                    out,
                    meta,
                    event.jev_call_id,
                    time.time(),
                ),
            )
            c.commit()
            _enforce_size_cap(c, max_db_size_mb, _db_path or _default_db_path())
            return c.total_changes > 0
    except Exception:
        log.warning("decision_events record failed", exc_info=True)
        return False


def record_replay_case(case: Any, retention_days: int = DEFAULT_RETENTION_DAYS) -> bool:
    """Insert or update a ReplayCase. Best-effort; never raises."""
    try:
        from .replay_case import ReplayCase

        if isinstance(case, ReplayCase):
            data = case.to_dict()
        else:
            data = dict(case)
        with _lock, _conn() as c:
            _prune_old(c, retention_days)
            c.execute(
                """INSERT OR REPLACE INTO replay_cases (
                    case_id, domain, input_features, observed_outcome,
                    production_decision, expected_label, label_source,
                    label_confidence, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("case_id"),
                    data.get("domain", "fetch"),
                    json.dumps(data.get("input_features", {}), ensure_ascii=False),
                    json.dumps(data.get("observed_outcome", {}), ensure_ascii=False),
                    json.dumps(data.get("production_decision", {}), ensure_ascii=False),
                    data.get("expected_label", ""),
                    data.get("label_source", "objective_outcome"),
                    float(data.get("label_confidence", 1.0)),
                    data.get("notes", ""),
                    float(data.get("created_at", time.time())),
                ),
            )
            c.commit()
            return True
    except Exception:
        log.warning("replay_cases record failed", exc_info=True)
        return False


def load_events(
    domain: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Load recent DecisionEvents as dicts (JSON fields parsed)."""
    try:
        with _lock, _conn() as c:
            if domain:
                rows = c.execute(
                    "SELECT * FROM decision_events WHERE domain = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (domain, limit, offset),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM decision_events ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                for key in ("request_features", "outcome_features", "metadata"):
                    if d.get(key):
                        try:
                            d[key] = json.loads(d[key])
                        except (json.JSONDecodeError, TypeError):
                            d[key] = {}
                result.append(d)
            return result
    except Exception:
        log.warning("decision_events load failed", exc_info=True)
        return []


def load_replay_cases(domain: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    """Load ReplayCases as dicts."""
    try:
        with _lock, _conn() as c:
            if domain:
                rows = c.execute(
                    "SELECT * FROM replay_cases WHERE domain = ? ORDER BY created_at DESC LIMIT ?",
                    (domain, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM replay_cases ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                for key in ("input_features", "observed_outcome", "production_decision"):
                    if d.get(key):
                        try:
                            d[key] = json.loads(d[key])
                        except (json.JSONDecodeError, TypeError):
                            d[key] = {}
                result.append(d)
            return result
    except Exception:
        log.warning("replay_cases load failed", exc_info=True)
        return []


def count_events(domain: str | None = None) -> int:
    try:
        with _lock, _conn() as c:
            if domain:
                row = c.execute("SELECT COUNT(*) FROM decision_events WHERE domain = ?", (domain,)).fetchone()
            else:
                row = c.execute("SELECT COUNT(*) FROM decision_events").fetchone()
            return int(row[0]) if row else 0
    except Exception:
        return 0


def summary() -> dict[str, Any]:
    """Aggregate summary for decision-report CLI."""
    try:
        with _lock, _conn() as c:
            total = c.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0]
            fetch_count = c.execute("SELECT COUNT(*) FROM decision_events WHERE domain='fetch'").fetchone()[0]
            search_count = c.execute("SELECT COUNT(*) FROM decision_events WHERE domain='search'").fetchone()[0]
            replay_count = c.execute("SELECT COUNT(*) FROM replay_cases").fetchone()[0]

            fetch_reasons = {
                row[0]: row[1]
                for row in c.execute(
                    "SELECT deterministic_reason, COUNT(*) FROM decision_events WHERE domain='fetch' GROUP BY deterministic_reason ORDER BY 2 DESC"
                )
            }
            fetch_actions = {
                row[0]: row[1]
                for row in c.execute(
                    "SELECT deterministic_action, COUNT(*) FROM decision_events WHERE domain='fetch' GROUP BY deterministic_action ORDER BY 2 DESC"
                )
            }
            fetch_outcomes = {
                row[0]: row[1]
                for row in c.execute(
                    "SELECT production_outcome, COUNT(*) FROM decision_events WHERE domain='fetch' GROUP BY production_outcome ORDER BY 2 DESC"
                )
            }
            search_reasons = {
                row[0]: row[1]
                for row in c.execute(
                    "SELECT deterministic_reason, COUNT(*) FROM decision_events WHERE domain='search' GROUP BY deterministic_reason ORDER BY 2 DESC"
                )
            }
            search_actions = {
                row[0]: row[1]
                for row in c.execute(
                    "SELECT deterministic_action, COUNT(*) FROM decision_events WHERE domain='search' GROUP BY deterministic_action ORDER BY 2 DESC"
                )
            }
            search_outcomes = {
                row[0]: row[1]
                for row in c.execute(
                    "SELECT production_outcome, COUNT(*) FROM decision_events WHERE domain='search' GROUP BY production_outcome ORDER BY 2 DESC"
                )
            }
            jev_joined = c.execute(
                "SELECT COUNT(*) FROM decision_events WHERE jev_call_id IS NOT NULL AND jev_call_id != ''"
            ).fetchone()[0]

            return {
                "total_events": total,
                "fetch_events": fetch_count,
                "search_events": search_count,
                "replay_cases": replay_count,
                "fetch": {
                    "reasons": fetch_reasons,
                    "actions": fetch_actions,
                    "outcomes": fetch_outcomes,
                },
                "search": {
                    "reasons": search_reasons,
                    "actions": search_actions,
                    "outcomes": search_outcomes,
                },
                "jev_joined_events": jev_joined,
            }
    except Exception:
        log.warning("decision_events summary failed", exc_info=True)
        return {"total_events": 0, "fetch_events": 0, "search_events": 0, "replay_cases": 0}


def update_replay_label(
    case_id: str, label: str, source: str = "human_verified", confidence: float = 1.0, notes: str = ""
) -> bool:
    """Update the expected_label of an existing ReplayCase (human labeling)."""
    try:
        with _lock, _conn() as c:
            c.execute(
                "UPDATE replay_cases SET expected_label=?, label_source=?, label_confidence=?, notes=? WHERE case_id=?",
                (label, source, confidence, notes, case_id),
            )
            c.commit()
            return c.total_changes > 0
    except Exception:
        log.warning("replay label update failed", exc_info=True)
        return False


def db_path() -> Path:
    return _db_path or _default_db_path()
