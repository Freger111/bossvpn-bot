"""Пользователи, заказы, ключи и подписки (SQLite)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    username   TEXT NOT NULL DEFAULT '',
    ref_id     INTEGER,
    balance    INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS keys_pool (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_code  TEXT NOT NULL,
    payload    TEXT NOT NULL,
    comment    TEXT NOT NULL DEFAULT '',
    used       INTEGER NOT NULL DEFAULT 0,
    order_id   INTEGER,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    plan_code    TEXT NOT NULL,
    title        TEXT NOT NULL,
    price        INTEGER NOT NULL,
    days         INTEGER NOT NULL,
    balance_used INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'new',
    created_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS subs (
    user_id    INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    payload    TEXT NOT NULL,
    PRIMARY KEY (user_id)
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, path: Path | str):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(SCHEMA)
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(orders)")}
            if "balance_used" not in cols:
                self.db.execute(
                    "ALTER TABLE orders ADD COLUMN balance_used INTEGER NOT NULL DEFAULT 0")
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(keys_pool)")}
            if "comment" not in cols:
                self.db.execute(
                    "ALTER TABLE keys_pool ADD COLUMN comment TEXT NOT NULL DEFAULT ''")
            self.db.commit()

    # ---------- пользователи ----------
    def ensure_user(self, user_id: int, username: str = "", ref_id: int | None = None) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO users(id, username, ref_id, created_at) VALUES(?,?,?,?)",
                    (user_id, username, ref_id, int(time.time())))
                self.db.commit()
                row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            elif username and row["username"] != username:
                self.db.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
                self.db.commit()
            return dict(row)

    def add_balance(self, user_id: int, amount: int) -> None:
        with self.lock:
            self.db.execute("UPDATE users SET balance = balance + ? WHERE id = ?",
                            (amount, user_id))
            self.db.commit()

    # ---------- ключи ----------
    def add_keys(self, plan_code: str, payloads: list[str]) -> int:
        now = int(time.time())
        with self.lock:
            self.db.executemany(
                "INSERT INTO keys_pool(plan_code, payload, created_at) VALUES(?,?,?)",
                [(plan_code, p, now) for p in payloads])
            self.db.commit()
        return len(payloads)

    def keys_left(self, plan_code: str) -> int:
        with self.lock:
            row = self.db.execute(
                "SELECT COUNT(*) c FROM keys_pool WHERE plan_code = ? AND used = 0",
                (plan_code,)).fetchone()
        return int(row["c"]) if row else 0

    def pool(self, plan_code: str | None = None) -> list[dict]:
        sql = "SELECT * FROM keys_pool"
        args: list = []
        if plan_code:
            sql += " WHERE plan_code = ?"
            args.append(plan_code)
        sql += " ORDER BY used, id"
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def set_comment(self, uuid: str, comment: str) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE keys_pool SET comment = ? WHERE payload LIKE ?",
                (comment, f"vless://{uuid}@%"))
            self.db.commit()

    def take_key(self, plan_code: str, order_id: int) -> str | None:
        with self.lock:
            row = self.db.execute(
                "SELECT id, payload FROM keys_pool WHERE plan_code = ? AND used = 0"
                " ORDER BY id LIMIT 1", (plan_code,)).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE keys_pool SET used = 1, order_id = ? WHERE id = ?",
                            (order_id, row["id"]))
            self.db.commit()
            return row["payload"]

    # ---------- заказы ----------
    def create_order(self, user_id: int, plan: dict, price: int | None = None,
                     balance_used: int = 0) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO orders(user_id, plan_code, title, price, days, balance_used,"
                " created_at) VALUES(?,?,?,?,?,?,?)",
                (user_id, plan["code"], plan["title"],
                 plan["price"] if price is None else price, plan["days"],
                 balance_used, int(time.time())))
            self.db.commit()
            return int(cur.lastrowid)

    def order(self, order_id: int) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return dict(row) if row else {}

    def set_status(self, order_id: int, status: str) -> None:
        with self.lock:
            self.db.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
            self.db.commit()

    def pending_orders(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM orders WHERE status IN ('new','awaiting') ORDER BY id DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_orders(self, limit: int = 20) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        with self.lock:
            paid = self.db.execute(
                "SELECT COUNT(*) c, COALESCE(SUM(price),0) s FROM orders"
                " WHERE status = 'paid'").fetchone()
            users = self.db.execute("SELECT COUNT(*) c FROM users").fetchone()
            active = self.db.execute(
                "SELECT COUNT(*) c FROM subs WHERE expires_at > ?",
                (int(time.time()),)).fetchone()
        return {"paid_orders": int(paid["c"]), "revenue": int(paid["s"]),
                "users": int(users["c"]), "active_subs": int(active["c"])}

    # ---------- подписка ----------
    def grant(self, user_id: int, days: int, payload: str) -> int:
        now = int(time.time())
        with self.lock:
            row = self.db.execute("SELECT * FROM subs WHERE user_id = ?", (user_id,)).fetchone()
            base = max(now, int(row["expires_at"])) if row else now
            expires = base + days * 86400
            if row:
                self.db.execute(
                    "UPDATE subs SET expires_at = ?, payload = ? WHERE user_id = ?",
                    (expires, payload, user_id))
            else:
                self.db.execute(
                    "INSERT INTO subs(user_id, expires_at, payload) VALUES(?,?,?)",
                    (user_id, expires, payload))
            self.db.commit()
            return expires

    def sub(self, user_id: int) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM subs WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else {}

    def user(self, user_id: int) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else {}

    def setting(self, key: str, default: str = "") -> str:
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO settings(key, value) VALUES(?,?)"
                            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                            (key, value))
            self.db.commit()
