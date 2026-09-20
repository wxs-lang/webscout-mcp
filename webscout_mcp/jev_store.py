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
    """Resolve the default DB path. Prefer explicit env, then a stable
    user-level data dir (independent of CWD), so that launching WebScout
    from different working directories still writes to one DB.

    Priority:
      1. ``WEBSCOUT_JEV_DB`` (or ``JEV_DB``) env var
      2. ``${XDG_DATA_HOME:-~/.local/share}/webscout/jev_shadow.db``
    """
    env = os.environ.get("WEBSCOUT_JEV_DB") or os.environ.get("JEV_DB")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".local" / "share")
    return base / "webscout" / "jev_shadow.db"


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


_SCHEMA_BASE = """
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
    input_tokens INTEGER,
    output_tokens INTEGER,
    rule_decision INTEGER,
    rule_reason TEXT,
    backend TEXT,
    content_length INTEGER,
    actual_route TEXT,
    browser_attempted INTEGER,
    browser_success INTEGER,
    error_code TEXT,
    position INTEGER,
    search_provider TEXT,
    schema_version TEXT,
    jev_call_id TEXT,
    run_id TEXT,
    model_requested TEXT,
    model_resolved TEXT
);
"""

_SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_jev_ts ON jev_records(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jev_q ON jev_records(jev_question, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jev_provider ON jev_records(jev_provider, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_jev_call ON jev_records(jev_call_id);
CREATE INDEX IF NOT EXISTS idx_jev_run ON jev_records(run_id);
"""

# v2 columns added by migration (CREATE TABLE above already includes them
# for fresh DBs; this list is for upgrading existing v1 databases).
_V2_COLUMNS: list[tuple[str, str]] = [
    ("jev_call_id", "TEXT"),
    ("run_id", "TEXT"),
    ("model_requested", "TEXT"),
    ("model_resolved", "TEXT"),
]


def _init_schema(path: Path) -> None:
    with sqlite3.connect(str(path), timeout=5.0) as c:
        c.executescript(_SCHEMA_BASE)
        # Idempotent v1 -> v2 migration: ALTER TABLE only for missing columns.
        existing = {row[1] for row in c.execute("PRAGMA table_info(jev_records)")}
        for col, ddl in _V2_COLUMNS:
            if col not in existing:
                c.execute(f"ALTER TABLE jev_records ADD COLUMN {col} {ddl}")  # nosec B608
        # Create indexes AFTER columns exist (handles v1 -> v2 upgrade).
        c.executescript(_SCHEMA_INDEXES)
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
                    input_tokens, output_tokens,
                    rule_decision, rule_reason, backend, content_length,
                    actual_route, browser_attempted, browser_success,
                    error_code, position, search_provider, schema_version,
                    jev_call_id, run_id, model_requested, model_resolved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    rec.get("input_tokens"),
                    rec.get("output_tokens"),
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
                    rec.get("schema_version"),
                    rec.get("jev_call_id"),
                    rec.get("run_id"),
                    rec.get("model_requested"),
                    rec.get("model_resolved"),
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


def load_recent(
    limit: int = 30, provider: str | None = None, schema_version: str | None = None
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM jev_records"
    where: list[str] = []
    params: list[Any] = []
    if provider:
        where.append("jev_provider = ?")
        params.append(provider)
    if schema_version:
        where.append("schema_version = ?")
        params.append(schema_version)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def load_disagreements(
    limit: int = 50, provider: str | None = None, schema_version: str | None = None
) -> list[dict[str, Any]]:
    """Rows where rule_decision is not null and differs from jev_decision."""
    sql = """SELECT * FROM jev_records
             WHERE rule_decision IS NOT NULL
               AND jev_decision IS NOT NULL
               AND jev_error IS NULL
               AND rule_decision != jev_decision"""
    params: list[Any] = []
    if provider:
        sql += " AND jev_provider = ?"
        params.append(provider)
    if schema_version:
        sql += " AND schema_version = ?"
        params.append(schema_version)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def load_errors(
    limit: int = 100, provider: str | None = None, schema_version: str | None = None
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM jev_records WHERE jev_error IS NOT NULL AND jev_error != ''"
    params: list[Any] = []
    if provider:
        sql += " AND jev_provider = ?"
        params.append(provider)
    if schema_version:
        sql += " AND schema_version = ?"
        params.append(schema_version)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(sql, params).fetchall()
    return _rows_to_dicts(rows)


def load_summary(
    provider: str | None = None,
    schema_version: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Aggregate stats over rows (optionally filtered by provider + schema + run).

    Token usage and latency are deduplicated by jev_call_id: one TypeSafe
    system_one call may produce several decision rows (fetch asks 2 questions
    at once), and summing rows directly double-counts usage.
    """
    where_clauses: list[str] = []
    params: list[Any] = []
    if provider:
        where_clauses.append("jev_provider = ?")
        params.append(provider)
    if schema_version:
        where_clauses.append("schema_version = ?")
        params.append(schema_version)
    if run_id:
        where_clauses.append("run_id = ?")
        params.append(run_id)
    where = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    with _conn() as c:
        total = c.execute(f"SELECT COUNT(*) AS n FROM jev_records{where}", params).fetchone()["n"]  # nosec B608
        success = c.execute(
            f"SELECT COUNT(*) AS n FROM jev_records{where} AND (jev_error IS NULL OR jev_error = '')"  # nosec B608
            if where_clauses
            else "SELECT COUNT(*) AS n FROM jev_records WHERE jev_error IS NULL OR jev_error = ''",
            params,
        ).fetchone()["n"]
        failure = total - success

        # API-call-level metrics: one row per distinct jev_call_id.
        call_where = where + (" AND " if where_clauses else " WHERE ") + "jev_call_id IS NOT NULL"
        call_rows = c.execute(
            f"""SELECT jev_call_id,
                       MAX(jev_latency_ms) AS latency_ms,
                       MAX(input_tokens) AS it,
                       MAX(output_tokens) AS ot,
                       MAX(CASE WHEN jev_error IS NULL OR jev_error='' THEN 0 ELSE 1 END) AS has_err,
                       MAX(CASE WHEN jev_error='timeout' THEN 1 ELSE 0 END) AS is_timeout,
                       MAX(model_requested) AS model_req,
                       MAX(model_resolved) AS model_res
                FROM jev_records{call_where}
                GROUP BY jev_call_id""",  # nosec B608
            params,
        ).fetchall()
        api_calls = len(call_rows)
        api_success = sum(1 for r in call_rows if r["has_err"] == 0)
        api_timeout = sum(1 for r in call_rows if r["is_timeout"] == 1)
        api_failed = api_calls - api_success
        call_latencies = sorted(r["latency_ms"] for r in call_rows if r["latency_ms"] is not None)
        in_tok = sum(r["it"] or 0 for r in call_rows)
        out_tok = sum(r["ot"] or 0 for r in call_rows)
        model_pairs = sorted({(r["model_req"], r["model_res"]) for r in call_rows if r["model_req"]})

        web_requests = c.execute(
            f"SELECT COUNT(DISTINCT trace_id) AS n FROM jev_records{where}",  # nosec B608
            params,
        ).fetchone()["n"]

        q = c.execute(
            f"""SELECT rule_decision, jev_decision, COUNT(*) AS n
                FROM jev_records
                WHERE jev_question='needs_escalation'
                  AND rule_decision IS NOT NULL
                  AND jev_decision IS NOT NULL
                  AND jev_error IS NULL
                  {("AND " + " AND ".join(where_clauses)) if where_clauses else ""}
                GROUP BY rule_decision, jev_decision""",  # nosec B608
            params,
        ).fetchall()
        provider_rows = c.execute(
            "SELECT jev_provider, COUNT(*) AS n FROM jev_records GROUP BY jev_provider"
        ).fetchall()
        schema_rows = c.execute(
            "SELECT schema_version, COUNT(*) AS n FROM jev_records GROUP BY schema_version"
        ).fetchall()
        run_rows = c.execute(
            "SELECT run_id, COUNT(*) AS n FROM jev_records WHERE run_id IS NOT NULL GROUP BY run_id"
        ).fetchall()
        dq = c.execute(
            f"""SELECT
                  SUM(CASE WHEN jev_error IS NULL OR jev_error='' THEN 1 ELSE 0 END) AS valid,
                  SUM(CASE WHEN jev_error IS NOT NULL AND jev_error!='' THEN 1 ELSE 0 END) AS invalid,
                  SUM(CASE WHEN jev_confidence IS NOT NULL THEN 1 ELSE 0 END) AS conf_ok,
                  SUM(CASE WHEN jev_confidence IS NULL THEN 1 ELSE 0 END) AS conf_missing,
                  SUM(CASE WHEN input_tokens IS NOT NULL THEN 1 ELSE 0 END) AS usage_ok,
                  SUM(CASE WHEN input_tokens IS NULL THEN 1 ELSE 0 END) AS usage_missing
                FROM jev_records{where}""",  # nosec B608
            params,
        ).fetchone()
        br = c.execute(
            f"""SELECT
                  SUM(COALESCE(browser_attempted,0)) AS attempted,
                  SUM(COALESCE(browser_success,0)) AS successes
                FROM jev_records{where}""",  # nosec B608
            params,
        ).fetchone()

    provider_dist = {r["jev_provider"] or "unknown": r["n"] for r in provider_rows}
    schema_dist = {r["schema_version"] or "unknown": r["n"] for r in schema_rows}
    run_dist = {r["run_id"]: r["n"] for r in run_rows}
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
        "decision_records": total,
        "webscout_requests": web_requests,
        "jev_api_calls": api_calls,
        "api_success": api_success,
        "api_timeout": api_timeout,
        "api_failed": api_failed,
        "calls": total,
        "success": success,
        "failure": failure,
        "latency_p50_ms": _pct(call_latencies, 0.5),
        "latency_p95_ms": _pct(call_latencies, 0.95),
        "quadrants": quadrants,
        "agreement_rate": round(agree / judged, 4) if judged else None,
        "judged_pairs": judged,
        "provider_distribution": provider_dist,
        "schema_versions": schema_dist,
        "run_versions": run_dist,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "valid_decisions": dq["valid"] or 0,
        "invalid_decisions": dq["invalid"] or 0,
        "confidence_available": dq["conf_ok"] or 0,
        "confidence_missing": dq["conf_missing"] or 0,
        "usage_available": dq["usage_ok"] or 0,
        "usage_missing": dq["usage_missing"] or 0,
        "browser_attempted": br["attempted"] or 0,
        "browser_success": br["successes"] or 0,
        "model_pairs": [f"{r or '?'}->{m or '?'}" for r, m in model_pairs],
    }


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    idx = min(len(values) - 1, int(len(values) * p))
    return round(values[idx], 2)
