"""The cache must not hold a file handle after an operation finishes.

## Measured, Windows 3.12.10

    with sqlite3.connect(db) as conn: ...  ->  shutil.rmtree(dir)  PermissionError WinError 32
    closing(sqlite3.connect(db))           ->  shutil.rmtree(dir)  OK

`with sqlite3.connect(...)` commits or rolls back and **does not close**. The handle keeps the
file open, so removing the cache directory - which test teardown does, and which a user
clearing app data does - fails on Windows. CI runs on Linux, where the same code happens to
work, which is why this survived.

`webscout_mcp/core/cache.py` opened seven connections this way.

## What these tests pin

The observable consequence rather than the mechanism: after using the cache, its directory can
be removed. That is the thing a user hits, and it stays true whatever the next refactor does
with the connection.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from webscout_mcp.core.cache import Cache


@pytest.fixture
def cache_dir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="webscout-cache-test-"))
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _can_remove(path: Path) -> tuple[bool, str]:
    try:
        shutil.rmtree(path)
        return True, ""
    except OSError as exc:  # Windows raises PermissionError (WinError 32)
        return False, f"{type(exc).__name__}: {exc}"


def test_a_used_cache_does_not_keep_its_directory_open(cache_dir):
    """The user-visible consequence: the cache dir must be removable afterwards."""
    db = cache_dir / "webscout.db"
    cache = Cache(db_path=db, ttl=60, max_size_mb=1)
    cache.set("https://example.com", "<html>hi</html>", "text/html")
    assert cache.get("https://example.com") is not None

    ok, detail = _can_remove(cache_dir)
    assert ok, f"the cache directory is still held open: {detail}"


def test_a_read_only_operation_releases_the_handle(cache_dir):
    """`get` opens a connection too; it must close it as well."""
    db = cache_dir / "webscout.db"
    writer = Cache(db_path=db, ttl=60, max_size_mb=1)
    writer.set("https://example.com", "<html>hi</html>", "text/html")
    del writer

    reader = Cache(db_path=db, ttl=60, max_size_mb=1)
    reader.get("https://example.com")
    ok, detail = _can_remove(cache_dir)
    assert ok, f"a read kept the file open: {detail}"


def test_clear_releases_the_handle(cache_dir):
    db = cache_dir / "webscout.db"
    cache = Cache(db_path=db, ttl=60, max_size_mb=1)
    cache.set("https://example.com", "<html>hi</html>", "text/html")
    cache.clear()
    ok, detail = _can_remove(cache_dir)
    assert ok, f"clear left the file open: {detail}"


def test_delete_releases_the_handle(cache_dir):
    db = cache_dir / "webscout.db"
    cache = Cache(db_path=db, ttl=60, max_size_mb=1)
    cache.set("https://example.com", "<html>hi</html>", "text/html")
    cache.delete("https://example.com")
    ok, detail = _can_remove(cache_dir)
    assert ok, f"delete left the file open: {detail}"


def test_the_bare_with_form_is_what_breaks():
    """Documents the trap, so the next person does not reintroduce it.

    This asserts the *problem* exists in the language, not that the code has it: it is the
    reason `closing()` is required around these connections.
    """
    path = Path(tempfile.mkdtemp(prefix="sqlite-bare-with-"))
    db = path / "t.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS x(a)")
        conn.commit()
    ok, _detail = _can_remove(path)
    shutil.rmtree(path, ignore_errors=True)
    if ok:
        pytest.skip("this platform releases the handle anyway; the defect is Windows-specific")
    assert not ok, "expected the bare `with` form to hold the handle"


def test_no_connection_in_the_cache_is_opened_with_a_bare_with():
    """Source-level, so a future edit cannot quietly regress it."""
    import inspect
    import re

    from webscout_mcp.core import cache as cache_module

    source = inspect.getsource(cache_module)
    offending = re.findall(r"with sqlite3\.connect\((?!.*closing)", source)
    assert not offending, f"{len(offending)} connection(s) still opened with a bare `with`, which does not close"
