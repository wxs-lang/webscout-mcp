"""SQLite-backed HTTP cache with TTL, size limits, and in-memory LRU layer."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional


class LRUCache:
    """A simple in-memory LRU cache with TTL support.

    Provides fast access to frequently-used entries without hitting SQLite.
    Entries are evicted in least-recently-used order when the cache exceeds
    ``max_size``.  Expired entries are lazily evicted on read.
    """

    def __init__(self, max_size: int = 128):
        self.max_size = max_size
        self._cache: OrderedDict[str, tuple[str, str, float, float]] = OrderedDict()
        # Statistics
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[tuple[str, str, float, float]]:
        """Retrieve an entry.  Returns None if missing or expired."""
        if key not in self._cache:
            self.misses += 1
            return None

        value, content_type, created_at, expires_at = self._cache[key]
        if expires_at < time.time():
            del self._cache[key]
            self.misses += 1
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self.hits += 1
        return (value, content_type, created_at, expires_at)

    def set(self, key: str, value: str, content_type: str, created_at: float, expires_at: float) -> None:
        """Store an entry, evicting LRU entries if needed."""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, content_type, created_at, expires_at)

        # Evict oldest entries if over capacity
        while len(self._cache) > self.max_size:
            self._cache.popitem(last=False)

    def delete(self, key: str) -> None:
        """Remove an entry if present."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all entries and reset statistics."""
        self._cache.clear()
        self.hits = 0
        self.misses = 0

    @property
    def size(self) -> int:
        """Current number of entries."""
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        """Cache hit rate (0.0 to 1.0)."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class Cache:
    """A layered cache: in-memory LRU + SQLite persistence.

    Keys are SHA-256 hashes of the URL (or query string).  Each entry has a
    TTL; expired entries are lazily evicted on read and proactively pruned
    when the cache exceeds ``max_size_mb``.

    The in-memory LRU layer provides sub-millisecond access to hot entries,
    while SQLite provides persistence across process restarts.
    """

    def __init__(
        self,
        db_path: Path,
        ttl: int = 7200,
        max_size_mb: int = 512,
        memory_cache_size: int = 128,
    ):
        self.db_path = db_path
        self.ttl = ttl
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._memory = LRUCache(max_size=memory_cache_size)
        self._init_db()

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    content_type TEXT,
                    size INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON cache(expires_at)")
            conn.commit()

    @staticmethod
    def _make_key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def get(self, url: str) -> Optional[dict]:
        """Retrieve a cached entry.  Returns None if missing or expired."""
        key = self._make_key(url)
        now = time.time()

        # Try memory cache first
        mem_entry = self._memory.get(key)
        if mem_entry is not None:
            value, content_type, created_at, expires_at = mem_entry
            return {
                "value": value,
                "content_type": content_type,
                "created_at": created_at,
                "cached": True,
                "cache_layer": "memory",
            }

        # Fall back to SQLite
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

        # Populate memory cache for future fast access
        self._memory.set(key, value, content_type, created_at, expires_at)

        return {
            "value": value,
            "content_type": content_type,
            "created_at": created_at,
            "cached": True,
            "cache_layer": "disk",
        }

    def set(
        self,
        url: str,
        value: str,
        content_type: str = "text/plain",
        ttl: Optional[int] = None,
    ) -> None:
        """Store a value in both memory and disk cache."""
        key = self._make_key(url)
        now = time.time()
        effective_ttl = ttl if ttl is not None else self.ttl
        expires_at = now + effective_ttl
        size = len(value.encode("utf-8"))

        # Write to memory cache
        self._memory.set(key, value, content_type, now, expires_at)

        # Write to SQLite
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
        """Remove an entry from both memory and disk cache."""
        key = self._make_key(url)
        self._memory.delete(key)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            conn.commit()

    def clear(self) -> int:
        """Clear all cache entries.  Returns the number deleted from disk."""
        self._memory.clear()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM cache")
            conn.commit()
            return cur.rowcount

    def stats(self) -> dict:
        """Return cache statistics including memory cache hit rate."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM cache").fetchone()
        count, total_size = row
        return {
            "entries": count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "max_size_mb": self.max_size_bytes // (1024 * 1024),
            "ttl_seconds": self.ttl,
            "memory_cache": {
                "entries": self._memory.size,
                "max_entries": self._memory.max_size,
                "hits": self._memory.hits,
                "misses": self._memory.misses,
                "hit_rate": round(self._memory.hit_rate, 4),
            },
        }

    def _prune_if_needed(self) -> None:
        """Evict oldest entries if cache exceeds max size."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COALESCE(SUM(size), 0) FROM cache").fetchone()[0]
            if total <= self.max_size_bytes:
                return
            # Delete oldest entries until under limit
            rows = conn.execute("SELECT key, size FROM cache ORDER BY created_at ASC").fetchall()
            running = total
            for key, size in rows:
                if running <= self.max_size_bytes:
                    break
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                # Also evict from memory cache
                self._memory._cache.pop(key, None)
                running -= size
            conn.commit()
