"""A tiny JSON key-value cache on top of SQLite.

Everything pulled from the network is cached here so that re-analysis, plotting,
and swapping LLM strategies never re-hit the API. (methodology: cache == raw data)
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any


class Cache:
    def __init__(self, path: str, enabled: bool = True):
        self.enabled = enabled
        self.path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if not self.enabled:
            return
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)"
        )
        self._conn.commit()

    def get(self, key: str) -> Any | None:
        if not self.enabled or self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

    def set(self, key: str, value: Any) -> None:
        if not self.enabled or self._conn is None:
            return
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, payload)
            )
            self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
