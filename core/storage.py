"""Пользователи, заказы, ключи и подписки (SQLite)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY,
    username   TEXT NOT NULL DEFAULT '',
    ref_id     INTEGER,
    balance    INTEGER NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT '',
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
    charge_id    TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'new',
    created_at   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS subs (
    user_id      INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL,
    payload      TEXT NOT NULL,
    reminded_day TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id)
);
CREATE TABLE IF NOT EXISTS reviews (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    rating     INTEGER NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    published  INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS promos (
    code       TEXT PRIMARY KEY,
    percent    INTEGER NOT NULL,
    max_uses   INTEGER NOT NULL DEFAULT 0,
    used       INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS promo_uses (
    code    TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (code, user_id)
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
            if "charge_id" not in cols:
                self.db.execute(
                    "ALTER TABLE orders ADD COLUMN charge_id TEXT NOT NULL DEFAULT ''")
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(subs)")}
            if "reminded_day" not in cols:
                self.db.execute(
                    "ALTER TABLE subs ADD COLUMN reminded_day TEXT NOT NULL DEFAULT ''")
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(users)")}
            if "source" not in cols:
                self.db.execute(
                    "ALTER TABLE users ADD COLUMN source TEXT NOT NULL DEFAULT ''")
            if "review_asked" not in cols:
                self.db.execute(
                    "ALTER TABLE users ADD COLUMN review_asked INTEGER NOT NULL DEFAULT 0")
            if "trial_used" not in cols:
                self.db.execute(
                    "ALTER TABLE users ADD COLUMN trial_used INTEGER NOT NULL DEFAULT 0")
            if "promo" not in cols:
                self.db.execute("ALTER TABLE users ADD COLUMN promo TEXT NOT NULL DEFAULT ''")
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(subs)")}
            if "winback_for" not in cols:
                self.db.execute(
                    "ALTER TABLE subs ADD COLUMN winback_for INTEGER NOT NULL DEFAULT 0")
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(keys_pool)")}
            if "comment" not in cols:
                self.db.execute(
                    "ALTER TABLE keys_pool ADD COLUMN comment TEXT NOT NULL DEFAULT ''")
            if "location" not in cols:
                self.db.execute(
                    "ALTER TABLE keys_pool ADD COLUMN location TEXT NOT NULL DEFAULT ''")
            self.db.execute("UPDATE keys_pool SET location = ? WHERE location = ''",
                            (config.DEFAULT_LOCATION,))
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(orders)")}
            if "location" not in cols:
                self.db.execute(
                    "ALTER TABLE orders ADD COLUMN location TEXT NOT NULL DEFAULT ''")
            if "promo" not in cols:
                self.db.execute("ALTER TABLE orders ADD COLUMN promo TEXT NOT NULL DEFAULT ''")
            self.db.commit()

    # ---------- пользователи ----------
    def ensure_user(self, user_id: int, username: str = "", ref_id: int | None = None,
                    source: str = "") -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO users(id, username, ref_id, source, created_at)"
                    " VALUES(?,?,?,?,?)",
                    (user_id, username, ref_id, source, int(time.time())))
                self.db.commit()
                row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            else:
                changed = False
                if username and row["username"] != username:
                    self.db.execute("UPDATE users SET username = ? WHERE id = ?",
                                    (username, user_id))
                    changed = True
                if source and not row["source"]:
                    self.db.execute("UPDATE users SET source = ? WHERE id = ?",
                                    (source, user_id))
                    changed = True
                if changed:
                    self.db.commit()
            return dict(row)

    def stats_by_source(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT source, COUNT(*) AS count FROM users GROUP BY source"
                " ORDER BY count DESC").fetchall()
        return [dict(r) for r in rows]

    def top_referrers(self, limit: int = 10) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT u2.id, u2.username, COUNT(*) AS invites, u2.balance"
                " FROM users u1 JOIN users u2 ON u1.ref_id = u2.id"
                " GROUP BY u2.id ORDER BY invites DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def add_balance(self, user_id: int, amount: int) -> None:
        with self.lock:
            self.db.execute("UPDATE users SET balance = balance + ? WHERE id = ?",
                            (amount, user_id))
            self.db.commit()

    # ---------- ключи ----------
    def add_keys(self, plan_code: str, payloads: list[str], location: str = "") -> int:
        now = int(time.time())
        location = location or config.DEFAULT_LOCATION
        with self.lock:
            self.db.executemany(
                "INSERT INTO keys_pool(plan_code, payload, location, created_at)"
                " VALUES(?,?,?,?)",
                [(plan_code, p, location, now) for p in payloads])
            self.db.commit()
        return len(payloads)

    def keys_left(self, plan_code: str, location: str = "") -> int:
        sql = "SELECT COUNT(*) c FROM keys_pool WHERE plan_code = ? AND used = 0"
        args: list = [plan_code]
        if location:
            sql += " AND location = ?"
            args.append(location)
        with self.lock:
            row = self.db.execute(sql, args).fetchone()
        return int(row["c"]) if row else 0

    def key_location(self, payload: str) -> str:
        with self.lock:
            row = self.db.execute("SELECT location FROM keys_pool WHERE payload = ? LIMIT 1",
                                  (payload,)).fetchone()
        return row["location"] if row and row["location"] else config.DEFAULT_LOCATION

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

    def take_key(self, plan_code: str, order_id: int, location: str = "") -> str | None:
        sql = "SELECT id, payload FROM keys_pool WHERE plan_code = ? AND used = 0"
        args: list = [plan_code]
        if location:
            sql += " AND location = ?"
            args.append(location)
        with self.lock:
            row = self.db.execute(sql + " ORDER BY id LIMIT 1", args).fetchone()
            if row is None:
                return None
            self.db.execute("UPDATE keys_pool SET used = 1, order_id = ? WHERE id = ?",
                            (order_id, row["id"]))
            self.db.commit()
            return row["payload"]

    # ---------- заказы ----------
    def create_order(self, user_id: int, plan: dict, price: int | None = None,
                     balance_used: int = 0, location: str = "", promo: str = "") -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO orders(user_id, plan_code, title, price, days, balance_used,"
                " location, promo, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (user_id, plan["code"], plan["title"],
                 plan["price"] if price is None else price, plan["days"],
                 balance_used, location, promo, int(time.time())))
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

    def set_charge(self, order_id: int, charge_id: str) -> None:
        with self.lock:
            self.db.execute("UPDATE orders SET charge_id = ? WHERE id = ?",
                            (charge_id, order_id))
            self.db.commit()

    def card_pending_orders(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM orders WHERE status = 'card_pending'").fetchall()
        return [dict(r) for r in rows]

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

    def set_reminded(self, user_id: int, day: str) -> None:
        with self.lock:
            self.db.execute("UPDATE subs SET reminded_day = ? WHERE user_id = ?",
                            (day, user_id))
            self.db.commit()

    def expiring_subs(self, days: int) -> list[dict]:
        now = int(time.time())
        deadline = now + days * 86400
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM subs WHERE expires_at > ? AND expires_at <= ?",
                (now, deadline)).fetchall()
        return [dict(r) for r in rows]

    def user(self, user_id: int) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else {}

    def has_paid(self, user_id: int) -> bool:
        with self.lock:
            row = self.db.execute("SELECT 1 FROM orders WHERE user_id = ? AND status = 'paid'"
                                  " LIMIT 1", (user_id,)).fetchone()
        return row is not None

    def set_trial_used(self, user_id: int) -> None:
        with self.lock:
            self.db.execute("UPDATE users SET trial_used = 1 WHERE id = ?", (user_id,))
            self.db.commit()

    # ---------- промокоды ----------
    def save_promo(self, code: str, percent: int, max_uses: int = 0) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO promos(code, percent, max_uses, created_at) VALUES(?,?,?,?)"
                " ON CONFLICT(code) DO UPDATE SET percent = excluded.percent,"
                " max_uses = excluded.max_uses",
                (code, percent, max_uses, int(time.time())))
            self.db.commit()

    def delete_promo(self, code: str) -> bool:
        with self.lock:
            cur = self.db.execute("DELETE FROM promos WHERE code = ?", (code,))
            self.db.commit()
        return cur.rowcount > 0

    def promo(self, code: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM promos WHERE code = ?", (code,)).fetchone()
        return dict(row) if row else {}

    def promos(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM promos ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def promo_used_by(self, code: str, user_id: int) -> bool:
        with self.lock:
            row = self.db.execute("SELECT 1 FROM promo_uses WHERE code = ? AND user_id = ?",
                                  (code, user_id)).fetchone()
        return row is not None

    def set_user_promo(self, user_id: int, code: str) -> None:
        with self.lock:
            self.db.execute("UPDATE users SET promo = ? WHERE id = ?", (code, user_id))
            self.db.commit()

    def use_promo(self, code: str, user_id: int) -> None:
        with self.lock:
            cur = self.db.execute("INSERT OR IGNORE INTO promo_uses(code, user_id) VALUES(?,?)",
                                  (code, user_id))
            if cur.rowcount:
                self.db.execute("UPDATE promos SET used = used + 1 WHERE code = ?", (code,))
            self.db.execute("UPDATE users SET promo = '' WHERE id = ? AND promo = ?",
                            (user_id, code))
            self.db.commit()

    # ---------- возврат ушедших ----------
    def winback_candidates(self, after_days: int, window_days: int = 30) -> list[dict]:
        now = int(time.time())
        with self.lock:
            rows = self.db.execute(
                "SELECT * FROM subs WHERE expires_at <= ? AND expires_at > ?"
                " AND winback_for != expires_at",
                (now - after_days * 86400, now - (after_days + window_days) * 86400)
            ).fetchall()
        return [dict(r) for r in rows]

    def set_winback(self, user_id: int, expires_at: int) -> None:
        with self.lock:
            self.db.execute("UPDATE subs SET winback_for = ? WHERE user_id = ?",
                            (expires_at, user_id))
            self.db.commit()

    # ---------- отзывы ----------
    def review_candidates(self, after_days: int) -> list[int]:
        """Покупатели, у которых первая оплата старше after_days и отзыв ещё не просили."""
        border = int(time.time()) - after_days * 86400
        with self.lock:
            rows = self.db.execute(
                "SELECT o.user_id FROM orders o JOIN users u ON u.id = o.user_id"
                " WHERE o.status = 'paid' AND u.review_asked = 0"
                " GROUP BY o.user_id HAVING MIN(o.created_at) <= ?", (border,)).fetchall()
        return [int(r["user_id"]) for r in rows]

    def set_review_asked(self, user_id: int) -> None:
        with self.lock:
            self.db.execute("UPDATE users SET review_asked = 1 WHERE id = ?", (user_id,))
            self.db.commit()

    def add_review(self, user_id: int, rating: int) -> int:
        with self.lock:
            cur = self.db.execute(
                "INSERT INTO reviews(user_id, rating, created_at) VALUES(?,?,?)",
                (user_id, rating, int(time.time())))
            self.db.commit()
            return int(cur.lastrowid)

    def set_review_text(self, review_id: int, text: str) -> None:
        with self.lock:
            self.db.execute("UPDATE reviews SET text = ? WHERE id = ?", (text, review_id))
            self.db.commit()

    def review(self, review_id: int) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM reviews WHERE id = ?",
                                  (review_id,)).fetchone()
        return dict(row) if row else {}

    def set_review_published(self, review_id: int) -> None:
        with self.lock:
            self.db.execute("UPDATE reviews SET published = 1 WHERE id = ?", (review_id,))
            self.db.commit()

    def review_stats(self) -> dict:
        with self.lock:
            rows = self.db.execute(
                "SELECT rating, COUNT(*) c FROM reviews GROUP BY rating").fetchall()
        dist = {int(r["rating"]): int(r["c"]) for r in rows}
        count = sum(dist.values())
        avg = sum(k * v for k, v in dist.items()) / count if count else 0.0
        return {"count": count, "avg": avg, "dist": dist}

    def recent_reviews(self, limit: int = 5) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT r.*, u.username FROM reviews r LEFT JOIN users u ON u.id = r.user_id"
                " WHERE r.text != '' ORDER BY r.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

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
