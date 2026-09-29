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
                last_price TEXT,
                last_currency TEXT,
                PRIMARY KEY (watch_name, item_id)
            )
            """)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(seen)").fetchall()}
        if "last_price" not in columns:
            self.conn.execute("ALTER TABLE seen ADD COLUMN last_price TEXT")
        if "last_currency" not in columns:
            self.conn.execute("ALTER TABLE seen ADD COLUMN last_currency TEXT")
        self.conn.commit()

    def is_new(self, watch_name: str, item_id: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM seen WHERE watch_name = ? AND item_id = ?",
            (watch_name, item_id),
        )
        return cur.fetchone() is None

    def get_last_price(self, watch_name: str, item_id: str) -> tuple[str | None, str | None]:
        cur = self.conn.execute(
            "SELECT last_price, last_currency FROM seen WHERE watch_name = ? AND item_id = ?",
            (watch_name, item_id),
        )
        row = cur.fetchone()
        return (None, None) if row is None else (row[0], row[1])

    def mark_seen(
        self,
        watch_name: str,
        item_id: str,
        last_price: str | None = None,
        last_currency: str | None = None,
    ) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO seen
               (watch_name, item_id, first_seen, last_price, last_currency)
               VALUES (?, ?, ?, ?, ?)""",
            (watch_name, item_id, int(time.time()), last_price, last_currency),
        )
        self.conn.commit()

    def update_last_price(
        self, watch_name: str, item_id: str, last_price: str, last_currency: str | None
    ) -> None:
        self.conn.execute(
            """UPDATE seen SET last_price = ?, last_currency = ?
               WHERE watch_name = ? AND item_id = ?""",
            (last_price, last_currency, watch_name, item_id),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
