"""SQLite-backed durable store for Jev Shadow records.

Location: ``<data_dir>/jev_shadow.db``.

Read-write from the recorder; read-only from the ``jev-report`` CLI.
The schema stores only fields that have already been sanitized upstream
(no cookies, no Authorization, no credentials, no full URLs with query
strings, no internal IP details).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .logging_config import get_logger

log = get_logger(__name__)

_lock = threading.Lock()
_db_path: Path | None = None


def _default_db_path() -> Path:
    """Resolve the default DB path. Prefer the runtime data dir if set,
    otherwise ``./data/jev_shadow.db`` next to the CWD."""
    env = os.environ.get("WEBSCOUT_JEV_DB")
    if env:
        return Path(env)
    return Path.cwd() / "data" / "jev_shadow.db"


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
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS jev_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    trace_id TEXT,
    operation TEXT NOT NULL,
    jev_question TEXT NOT NULL,
    jev_decision INTEGER,
    jev_probability REAL,
    jev_confidence REAL,
    jev_latency_ms REAL,
    jev_provider TEXT,
    jev_error TEXT,
    rule_decision INTEGER,
    rule_reason TEXT,
    backend TEXT,
    content_length INTEGER,
    actual_route TEXT,
    browser_attempted INTEGER,
    browser_success INTEGER,
    error_code TEXT,
    position INTEGER,
    search_provider TEXT
);
CREATE INDEX IF NOT EXISTS idx_jev_ts ON jev_records(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jev_q ON jev_records(jev_question, timestamp DESC);
"""


def _init_schema(path: Path) -> None:
    with sqlite3.connect(str(path), timeout=5.0) as c:
        c.executescript(_SCHEMA)
        c.commit()


def append_record(rec: dict[str, Any]) -> None:
    """Insert one shadow record. Best-effort; never raises."""
    try:
        with _lock, _conn() as c:
            c.execute(
                """INSERT INTO jev_records (
                    timestamp, trace_id, operation, jev_question,
                    jev_decision, jev_probability, jev_confidence,
                    jev_latency_ms, jev_provider, jev_error,
                    rule_decision, rule_reason, backend, content_length,
                    actual_route, browser_attempted, browser_success,
                    error_code, position, search_provider
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rec.get("timestamp"),
                    rec.get("trace_id"),
                    rec.get("operation"),
                    rec.get("jev_question"),
                    _int(rec.get("jev_decision")),
                    rec.get("jev_probability"),
                    rec.get("jev_confidence"),
                    rec.get("jev_latency_ms"),
                    rec.get("jev_provider"),
                    rec.get("jev_error"),
                    _int(rec.get("rule_decision")),
                    rec.get("rule_reason"),
                    rec.get("backend"),
                    rec.get("content_length"),
                    rec.get("actual_route"),
                    _int(rec.get("browser_attempted")),
                    _int(rec.get("browser_success")),
                    rec.get("error_code"),
                    rec.get("position"),
                    rec.get("search_provider"),
                ),
            )
            c.commit()
    except Exception:  # pragma: no cover - persistence must not break shadow
        log.debug("jev_store append failed", exc_info=True)


def _int(v: Any) -> int | None:
    if v is None:
        return None
    return 1 if bool(v) else 0


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        d = dict(r)
        for k in ("jev_decision", "rule_decision", "browser_attempted", "browser_success"):
            if d.get(k) is not None:
                d[k] = bool(d[k])
        out.append(d)
    return out


def load_recent(limit: int = 30) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM jev_records ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
    return _rows_to_dicts(rows)


def load_disagreements(limit: int = 50) -> list[dict[str, Any]]:
    """Rows where rule_decision is not null and differs from jev_decision."""
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM jev_records
               WHERE rule_decision IS NOT NULL
                 AND jev_decision IS NOT NULL
                 AND jev_error IS NULL
                 AND rule_decision != jev_decision
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return _rows_to_dicts(rows)


def load_errors(limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            """SELECT * FROM jev_records
               WHERE jev_error IS NOT NULL OR jev_error != ''
               ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return _rows_to_dicts(rows)


def load_summary() -> dict[str, Any]:
    """Aggregate stats over all rows."""
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM jev_records").fetchone()["n"]
        success = c.execute(
            "SELECT COUNT(*) AS n FROM jev_records WHERE jev_error IS NULL OR jev_error = ''"
        ).fetchone()["n"]
        failure = total - success
        latency_rows = c.execute("SELECT jev_latency_ms FROM jev_records WHERE jev_latency_ms IS NOT NULL").fetchall()
        latencies = sorted(r["jev_latency_ms"] for r in latency_rows)
        # Four-quadrant on needs_escalation only.
        q = c.execute(
            """SELECT rule_decision, jev_decision, COUNT(*) AS n
               FROM jev_records
               WHERE jev_question='needs_escalation'
                 AND rule_decision IS NOT NULL
                 AND jev_decision IS NOT NULL
                 AND jev_error IS NULL
               GROUP BY rule_decision, jev_decision"""
        ).fetchall()
    quadrants = {
        "rule_no/jev_no": 0,
        "rule_no/jev_yes": 0,
        "rule_yes/jev_no": 0,
        "rule_yes/jev_yes": 0,
    }
    for row in q:
        rd = bool(row["rule_decision"])
        jd = bool(row["jev_decision"])
        rd_s = "yes" if rd else "no"
        jd_s = "yes" if jd else "no"
        quadrants[f"rule_{rd_s}/jev_{jd_s}"] = row["n"]
    agree = quadrants["rule_yes/jev_yes"] + quadrants["rule_no/jev_no"]
    disagree = quadrants["rule_yes/jev_no"] + quadrants["rule_no/jev_yes"]
    judged = agree + disagree
    return {
        "calls": total,
        "success": success,
        "failure": failure,
        "latency_p50_ms": _pct(latencies, 0.5),
        "latency_p95_ms": _pct(latencies, 0.95),
        "quadrants": quadrants,
        "agreement_rate": round(agree / judged, 4) if judged else None,
        "judged_pairs": judged,
    }


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    idx = min(len(values) - 1, int(len(values) * p))
    return round(values[idx], 2)
