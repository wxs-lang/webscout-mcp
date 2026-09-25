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

from .decision_event import DecisionEvent, _scrub_dict, _scrub_text
from .logging_config import get_logger
from .replay_case import _validate_label_source

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
    label_time REAL,
    notes TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replay_domain ON replay_cases(domain);
CREATE INDEX IF NOT EXISTS idx_replay_label ON replay_cases(expected_label);
"""

_MIGRATIONS = [
    # (table, column, ddl)
    ("replay_cases", "label_time", "ALTER TABLE replay_cases ADD COLUMN label_time REAL"),
]


def _run_migrations(path: Path) -> None:
    """Idempotent column migrations for existing DBs."""
    try:
        with sqlite3.connect(str(path), timeout=5.0) as c:
            for table, column, ddl in _MIGRATIONS:
                cols = {row[1] for row in c.execute(f"PRAGMA table_info({table})")}
                if column not in cols:
                    c.execute(ddl)
            c.commit()
    except Exception:
        log.warning("decision_events migration failed", exc_info=True)


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
        _run_migrations(path)
    except Exception:
        log.warning("decision_events schema init failed", exc_info=True)


def _prune_old(conn: sqlite3.Connection, retention_days: int) -> None:
    """Delete rows older than retention_days."""
    cutoff = time.time() - retention_days * 86400
    conn.execute("DELETE FROM decision_events WHERE created_at < ?", (cutoff,))
    conn.execute("DELETE FROM replay_cases WHERE created_at < ?", (cutoff,))


def _total_db_size(path: Path) -> int:
    """Total on-disk size: main DB + WAL file."""
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(path) + suffix)
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def _logical_used_bytes(conn: sqlite3.Connection) -> int:
    """Compute logical data size: (page_count - freelist_count) * page_size.

    This reflects actual data, not the physical file which may retain freed
    pages until VACUUM. Used as the DELETE-loop progress condition so we
    don't delete until the file shrinks (which only happens at VACUUM).
    """
    try:
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        freelist = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        return max(0, (page_count - freelist) * page_size)
    except sqlite3.Error:
        return 0


def _enforce_size_cap(conn: sqlite3.Connection, max_mb: int, db_path: Path, *, force_vacuum: bool = False) -> None:
    """Size-cap maintenance with logical-page-based pruning and hysteresis.

    High watermark (110% of cap): trigger maintenance.
    Target (90% of cap): stop deleting.
    VACUUM: only after pruning, if physical size still > high watermark.

    The DELETE loop uses LOGICAL used bytes (page_count - freelist_count) as
    its progress condition, NOT physical file size. SQLite does not shrink
    the file on DELETE; using physical size would cause delete-until-empty.
    """
    try:
        max_bytes = max_mb * 1024 * 1024
        high_watermark = int(max_bytes * 1.10)
        target_bytes = int(max_bytes * 0.90)

        # Checkpoint WAL first so page_count reflects committed data.
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error:
            pass

        # Only trigger if physical size exceeds high watermark (or forced).
        physical = _total_db_size(db_path)
        if physical <= high_watermark and not force_vacuum:
            return

        # Phase A: prune oldest rows until logical usage <= target.
        deleted_any = False
        max_iterations = 50  # safety bound against infinite loops
        for _ in range(max_iterations):
            logical = _logical_used_bytes(conn)
            if logical <= target_bytes:
                break
            ev_count = conn.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0]
            rp_count = conn.execute("SELECT COUNT(*) FROM replay_cases").fetchone()[0]
            if ev_count == 0 and rp_count == 0:
                break
            total = ev_count + rp_count
            # Delete 5-10% from each table proportionally.
            batch = max(1, total // 10)
            if ev_count > 0:
                ev_delete = max(1, int(ev_count / total * batch))
                conn.execute(
                    "DELETE FROM decision_events WHERE id IN (SELECT id FROM decision_events ORDER BY created_at ASC LIMIT ?)",
                    (ev_delete,),
                )
                deleted_any = True
            if rp_count > 0:
                rp_delete = max(1, int(rp_count / total * batch))
                conn.execute(
                    "DELETE FROM replay_cases WHERE id IN (SELECT id FROM replay_cases ORDER BY created_at ASC LIMIT ?)",
                    (rp_delete,),
                )
                deleted_any = True
            conn.commit()

        # Phase B: checkpoint + VACUUM if still materially over cap.
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass

        if force_vacuum or (_total_db_size(db_path) > high_watermark and deleted_any):
            try:
                conn.execute("VACUUM")
                conn.commit()
            except sqlite3.Error:
                pass
    except Exception:
        log.warning("decision_events size cap enforcement failed", exc_info=True)


def record_event(
    event: DecisionEvent, retention_days: int = DEFAULT_RETENTION_DAYS, max_db_size_mb: int | None = None
) -> bool:
    """Insert one DecisionEvent. Best-effort; never raises.

    Returns True if the record was written, False otherwise (including
    duplicate event_id).
    """
    try:
        if max_db_size_mb is None:
            max_db_size_mb = DEFAULT_MAX_DB_SIZE_MB
        with _lock, _conn() as c:
            _prune_old(c, retention_days)
            req = json.dumps(_scrub_dict(event.request_features), ensure_ascii=False)
            out = json.dumps(_scrub_dict(event.outcome_features), ensure_ascii=False)
            meta = json.dumps(_scrub_dict(event.metadata), ensure_ascii=False)
            cur = c.execute(
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
            inserted = cur.rowcount > 0
            c.commit()
            _enforce_size_cap(c, max_db_size_mb, _db_path or _default_db_path())
            return inserted
    except Exception:
        log.warning("decision_events record failed", exc_info=True)
        return False


def record_replay_case(case: Any, retention_days: int = DEFAULT_RETENTION_DAYS) -> bool:
    """Insert or update a ReplayCase. Best-effort; never raises.

    Strictly validates label_source (jev_verified rejected). Scrubs
    input_features / observed_outcome / production_decision / notes
    at the store layer.
    """
    try:
        from .replay_case import ReplayCase

        if isinstance(case, ReplayCase):
            data = case.to_dict()
        else:
            data = dict(case)
        # Strict label_source validation BEFORE writing.
        label_source = _validate_label_source(data.get("label_source", "objective_outcome"))
        data["label_source"] = label_source.value

        # Store-level scrub: all dict fields + notes text.
        input_features = json.dumps(_scrub_dict(data.get("input_features", {})), ensure_ascii=False)
        observed_outcome = json.dumps(_scrub_dict(data.get("observed_outcome", {})), ensure_ascii=False)
        production_decision = json.dumps(_scrub_dict(data.get("production_decision", {})), ensure_ascii=False)
        notes = _scrub_text(data.get("notes", ""))

        label_time = data.get("label_time")
        if label_time is not None:
            label_time = float(label_time)

        with _lock, _conn() as c:
            _prune_old(c, retention_days)
            c.execute(
                """INSERT OR REPLACE INTO replay_cases (
                    case_id, domain, input_features, observed_outcome,
                    production_decision, expected_label, label_source,
                    label_confidence, label_time, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("case_id"),
                    data.get("domain", "fetch"),
                    input_features,
                    observed_outcome,
                    production_decision,
                    data.get("expected_label", ""),
                    data["label_source"],
                    float(data.get("label_confidence", 1.0)),
                    label_time,
                    notes,
                    float(data.get("created_at", time.time())),
                ),
            )
            c.commit()
            _enforce_size_cap(c, DEFAULT_MAX_DB_SIZE_MB, _db_path or _default_db_path())
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
        # Collect all decision DB data inside the lock.
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

        # Lock released — join_report() acquires its own lock (would deadlock otherwise).
        # Eligibility-aware Jev correlation via join_report().
        # jev_joined_events is deprecated (based on jev_call_id); kept for
        # backward compatibility. Authoritative metrics are in jev_correlation.
        try:
            jev_corr = join_report()
        except Exception:
            jev_corr = {"join_coverage": 0.0, "eligible_decisions": 0, "joined_eligible": 0}

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
            "jev_joined_events": jev_joined,  # deprecated: use jev_correlation
            "jev_correlation": jev_corr,
        }
    except Exception:
        log.warning("decision_events summary failed", exc_info=True)
        return {"total_events": 0, "fetch_events": 0, "search_events": 0, "replay_cases": 0}


def update_replay_label(
    case_id: str, label: str, source: str = "human_verified", confidence: float = 1.0, notes: str = ""
) -> bool:
    """Update the expected_label of an existing ReplayCase (human labeling).

    Strictly validates label_source. Sets label_time to current UTC epoch.
    Scrubs notes of secrets.
    """
    try:
        label_source = _validate_label_source(source)
        notes_clean = _scrub_text(notes)
        with _lock, _conn() as c:
            c.execute(
                "UPDATE replay_cases SET expected_label=?, label_source=?, label_confidence=?, label_time=?, notes=? WHERE case_id=?",
                (label, label_source.value, confidence, time.time(), notes_clean, case_id),
            )
            c.commit()
            return c.total_changes > 0
    except Exception:
        log.warning("replay label update failed", exc_info=True)
        return False


def join_report() -> dict[str, Any]:
    """Read-only join report between DecisionEvents and Jev Shadow records.

    Join key: (run_id, trace_id). Does NOT copy Jev state into Decision DB.
    Eligibility-aware: only DecisionEvents with metadata.jev_eligible=true
    count toward the correlation denominator. Snapshot hits, cache hits,
    EMPTY/ERROR/STOP are intentionally unjoined (not correlation failures).
    """
    try:
        from .jev_store import db_path as jev_db_path

        decision_pairs: set[tuple[str, str]] = set()
        eligible_pairs: set[tuple[str, str]] = set()
        decision_by_domain: dict[str, dict[str, set]] = {
            "fetch": {"all": set(), "eligible": set()},
            "search": {"all": set(), "eligible": set()},
        }
        with _lock, _conn() as c:
            rows = c.execute(
                "SELECT DISTINCT run_id, trace_id, domain, metadata FROM decision_events WHERE run_id != '' AND trace_id != ''"
            ).fetchall()
            for row in rows:
                pair = (row["run_id"], row["trace_id"])
                decision_pairs.add(pair)
                d = row["domain"]
                if d in decision_by_domain:
                    decision_by_domain[d]["all"].add(pair)
                # Check eligibility from metadata JSON.
                eligible = False
                try:
                    meta = json.loads(row["metadata"]) if row["metadata"] else {}
                    eligible = bool(meta.get("jev_eligible", False))
                except (json.JSONDecodeError, TypeError):
                    pass
                if eligible:
                    eligible_pairs.add(pair)
                    if d in decision_by_domain:
                        decision_by_domain[d]["eligible"].add(pair)

        jev_pairs: set[tuple[str, str]] = set()
        jev_by_operation: dict[str, set] = {"fetch": set(), "search": set()}
        jev_db = jev_db_path()
        if jev_db.exists():
            try:
                with sqlite3.connect(str(jev_db), timeout=5.0) as jc:
                    jc.row_factory = sqlite3.Row
                    jrows = jc.execute(
                        "SELECT DISTINCT run_id, trace_id, operation FROM jev_records WHERE run_id IS NOT NULL AND run_id != '' AND trace_id IS NOT NULL AND trace_id != ''"
                    ).fetchall()
                    for row in jrows:
                        pair = (row["run_id"], row["trace_id"])
                        jev_pairs.add(pair)
                        op = row["operation"]
                        if op in jev_by_operation:
                            jev_by_operation[op].add(pair)
            except Exception:
                log.warning("join_report: jev db read failed", exc_info=True)

        joined = decision_pairs & jev_pairs
        joined_eligible = eligible_pairs & jev_pairs
        unjoined_decisions = decision_pairs - jev_pairs
        orphan_jev = jev_pairs - decision_pairs
        intentional_unjoined = decision_pairs - eligible_pairs
        unexpected_unjoined = eligible_pairs - jev_pairs

        total_eligible = len(eligible_pairs)
        eligible_coverage = len(joined_eligible) / total_eligible if total_eligible else 0.0

        by_domain: dict[str, dict[str, Any]] = {}
        for domain in ("fetch", "search"):
            d_all = decision_by_domain[domain]["all"]
            d_eligible = decision_by_domain[domain]["eligible"]
            j_domain = jev_by_operation.get(domain, set())
            d_joined = d_all & j_domain
            d_eligible_joined = d_eligible & j_domain
            cov = len(d_eligible_joined) / len(d_eligible) if d_eligible else 0.0
            by_domain[domain] = {
                "decision_events": len(d_all),
                "eligible_decisions": len(d_eligible),
                "jev_records": len(j_domain),
                "joined_pairs": len(d_joined),
                "joined_eligible": len(d_eligible_joined),
                "unjoined_decisions": len(d_all - j_domain),
                "orphan_jev": len(j_domain - d_all),
                "intentional_unjoined": len(d_all - d_eligible),
                "unexpected_unjoined": len(d_eligible - j_domain),
                "join_coverage": round(cov, 4),
            }

        return {
            "total_decisions": len(decision_pairs),
            "eligible_decisions": total_eligible,
            "advisor_enabled_decisions": total_eligible,  # eligible path = would fire Jev if enabled
            "joined_decisions": len(joined),
            "joined_eligible": len(joined_eligible),
            "intentional_unjoined": len(intentional_unjoined),
            "unexpected_unjoined": len(unexpected_unjoined),
            "unjoined_decision_pairs": len(unjoined_decisions),
            "orphan_jev_pairs": len(orphan_jev),
            "join_coverage": round(eligible_coverage, 4),
            "by_domain": by_domain,
        }
    except Exception:
        log.warning("join_report failed", exc_info=True)
        return {"total_decisions": 0, "eligible_decisions": 0, "joined_eligible": 0, "join_coverage": 0.0}


def db_path() -> Path:
    return _db_path or _default_db_path()
