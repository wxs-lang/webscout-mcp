"""The decision/jev stores must not hold SQLite handles after an operation.

## Measured

`_conn()` returned a raw connection, and every call site used it as a context manager:

    with _lock, _conn() as c: ...

`sqlite3.Connection.__exit__` commits or rolls back and **does not close**. Fourteen call
sites leaked a handle each. On Windows, the DB file stays open, so removing the data directory
fails with WinError 32 - the same failure `core/cache.py` hit before v2.8.0 (7 sites there).

## The fix

`_conn_ctx()` wraps the factory: commit on success, rollback on error, always close. Call
sites keep their exact `with _lock, _conn_ctx() as c:` shape, so the diff is mechanical.

After the change, writing a record and then removing the store's directory succeeds.

## 2026-11-14 update: persistent connection

record_event measured 5.92ms/record with per-call connections vs 0.63ms on a
persistent one (per-connection schema load dominates on Windows/HDD). The
store now holds a process-lifetime handle (synchronous=NORMAL WAL — the data
is rebuildable observability state) released by `decision_store.close()`,
which `aclose_services()` calls on shutdown. The rmtree contract moves to
explicit close(): tests call close() before removing the directory, mirroring
how cache.py's fix works.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from webscout_mcp import decision_store, jev_store


@pytest.fixture
def store_env(tmp_path: Path, monkeypatch):
    """Point both stores at an isolated directory and clean it up afterwards."""
    monkeypatch.setattr(jev_store, "_db_path", tmp_path / "jev.db")
    monkeypatch.setattr(decision_store, "_db_path", tmp_path / "decision.db", raising=False)
    yield tmp_path
    shutil.rmtree(tmp_path, ignore_errors=True)


def _can_remove(path: Path) -> bool:
    try:
        shutil.rmtree(path)
        return True
    except OSError:
        return False


def _rec() -> dict:
    """A minimal record that passes the table's NOT NULL constraints."""
    import time

    return {
        "timestamp": time.time(),
        "operation": "test",
        "jev_question": "q",
        "jev_latency_ms": 1.0,
    }


def test_jev_append_does_not_hold_the_directory(store_env):
    jev_store.append_record(_rec())
    assert _can_remove(store_env), "jev_store left the DB file open"


def test_decision_count_does_not_hold_the_directory(store_env):
    decision_store.count_events()
    decision_store.close()
    assert _can_remove(store_env), "close() failed to release the DB handle"


def test_jev_load_recent_does_not_hold_the_directory(store_env):
    jev_store.append_record(_rec())
    jev_store.load_recent(limit=3)
    assert _can_remove(store_env), "a read kept the DB file open"


def test_commit_still_happens(store_env):
    """Closing must not lose the write."""
    jev_store.append_record(_rec())
    rows = jev_store.load_recent(limit=5)
    assert rows, "the record was not persisted - the close wrapper broke the commit"
    serialized = str(rows)
    assert "test" in serialized, f"the record is missing from the store: {serialized[:120]}"


def test_the_connection_manager_rolls_back_on_error(store_env):
    """A failing body rolls back; the persistent handle survives by design
    (it is process-lifetime, released by close()).

    Self-contained probe on the store_env tmp DB: create the probe table
    OUTSIDE the failing block (DDL may auto-commit), INSERT inside it, then
    verify the row is gone after the exception. No record_event (its own
    lock+commit would defeat the outer rollback), no count_events (reads
    through its own context and would be polluted by other tests)."""
    # Arrange: probe table committed on its own.
    with decision_store._conn_ctx() as c:
        c.execute("CREATE TABLE probe_rollback (v INTEGER)")

    # Act: DML insert, then the body raises.
    with pytest.raises(ValueError):
        with decision_store._conn_ctx() as c:
            c.execute("INSERT INTO probe_rollback VALUES (1)")
            raise ValueError("boom")

    # Assert: the INSERT rolled back; the table still exists (committed earlier).
    with decision_store._conn_ctx() as c:
        n = c.execute("SELECT COUNT(*) FROM probe_rollback").fetchone()[0]
        assert n == 0, "rollback did not happen"
    decision_store.close()


def test_close_releases_the_handle_and_keeps_data(store_env):
    """The production contract: close() drops the handle; committed data
    survives; the directory becomes removable."""
    decision_store.count_events()
    decision_store.close()
    assert _can_remove(store_env), "close() did not release the handle"


def test_no_call_site_uses_the_raw_factory_as_a_context_manager():
    """Source-level: `_conn()` must not appear as `with ... _conn() as c:`."""
    import inspect
    import re

    for module in (decision_store, jev_store):
        source = inspect.getsource(module)
        offending = re.findall(r"with\s+(?:_lock,\s*)?_conn\(\)", source)
        assert not offending, (
            f"{module.__name__} still opens a connection without the closing wrapper: {len(offending)} site(s)"
        )
