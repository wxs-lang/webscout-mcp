"""SQLite-backed HTTP cache with TTL and size limits."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional


class Cache:
    """A simple SQLite cache for storing fetched web content and search results.

    Keys are SHA-256 hashes of the URL (or query string).  Each entry has a
    TTL; expired entries are lazily evicted on read and proactively pruned
    when the cache exceeds ``max_size_mb``.
    """

    def __init__(self, db_path: Path, ttl: int = 7200, max_size_mb: int = 512):
        self.db_path = db_path
        self.ttl = ttl
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    content_type TEXT,
                    size INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)")
            conn.commit()

    @staticmethod
    def _make_key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def get(self, url: str) -> Optional[dict]:
        """Retrieve a cached entry.  Returns None if missing or expired."""
        key = self._make_key(url)
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT value, content_type, created_at, expires_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        value, content_type, created_at, expires_at = row
        if expires_at < now:
            self.delete(url)
            return None
        return {
            "value": value,
            "content_type": content_type,
            "created_at": created_at,
            "cached": True,
        }

    def set(self, url: str, value: str, content_type: str = "text/plain", ttl: Optional[int] = None) -> None:
        """Store a value in the cache."""
        key = self._make_key(url)
        now = time.time()
        effective_ttl = ttl if ttl is not None else self.ttl
        expires_at = now + effective_ttl
        size = len(value.encode("utf-8"))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache (key, value, content_type, size, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key, value, content_type, size, now, expires_at),
            )
            conn.commit()
        self._prune_if_needed()

    def delete(self, url: str) -> None:
        key = self._make_key(url)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()

    def clear(self) -> int:
        """Clear all cache entries.  Returns the number deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM cache")
            conn.commit()
            return cur.rowcount

    def stats(self) -> dict:
        """Return cache statistics."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM cache"
            ).fetchone()
        count, total_size = row
        return {
            "entries": count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "max_size_mb": self.max_size_bytes // (1024 * 1024),
            "ttl_seconds": self.ttl,
        }

    def _prune_if_needed(self) -> None:
        """Evict oldest entries if cache exceeds max size."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COALESCE(SUM(size), 0) FROM cache").fetchone()[0]
            if total <= self.max_size_bytes:
                return
            # Delete oldest entries until under limit
            rows = conn.execute(
                "SELECT key, size FROM cache ORDER BY created_at ASC"
            ).fetchall()
            running = total
            for key, size in rows:
                if running <= self.max_size_bytes:
                    break
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                running -= size
            conn.commit()
