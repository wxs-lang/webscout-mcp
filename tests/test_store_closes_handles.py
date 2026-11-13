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
    assert _can_remove(store_env), "decision_store left the DB file open"


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


def test_the_connection_manager_closes_on_error():
    """A failing body must roll back and close, not leave the handle behind."""
    with pytest.raises(ValueError):
        with decision_store._conn_ctx() as c:
            raise ValueError("boom")
    # The connection is closed: executing on it now raises ProgrammingError.
    with pytest.raises(sqlite3.ProgrammingError):
        c.execute("SELECT 1")


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
