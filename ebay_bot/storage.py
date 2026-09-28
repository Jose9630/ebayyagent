"""Keeps track of which item IDs we've already seen per watch, so we never
notify twice about the same listing (and survives restarts)."""

from __future__ import annotations

import sqlite3
import time


class SeenStore:
    def __init__(self, path: str = "seen_items.db"):
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS seen (
                watch_name TEXT,
                item_id TEXT,
                first_seen INTEGER,
                PRIMARY KEY (watch_name, item_id)
            )
            """)
        self.conn.commit()

    def is_new(self, watch_name: str, item_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen WHERE watch_name = ? AND item_id = ?",
            (watch_name, item_id),
        )
        return cur.fetchone() is None

    def mark_seen(self, watch_name: str, item_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen (watch_name, item_id, first_seen) VALUES (?, ?, ?)",
            (watch_name, item_id, int(time.time())),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
