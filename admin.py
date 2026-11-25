"""Управление VPN-ботом из консоли."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config, keyboards as kb  # noqa: E402
from core.storage import Storage  # noqa: E402


def split_items(raw: str) -> list[str]:
    if not raw:
        return []
    parts = raw.splitlines() if "\n" in raw else raw.split(",")
    return [p.strip() for p in parts if p.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Управление VPN-ботом")
    sub = parser.add_subparsers(dest="cmd", required=True)

    keys = sub.add_parser("keys", help="добавить ключи: --plan m1 --items 'vless://...'")
    keys.add_argument("--plan", required=True, choices=[p["code"] for p in config.PLANS])
    keys.add_argument("--items", required=True)

    sub.add_parser("list", help="остатки ключей")
    sub.add_parser("orders", help="последние заказы")
    sub.add_parser("stats", help="статистика")

    confirm = sub.add_parser("confirm", help="выдать ключ по заказу")
    confirm.add_argument("order_id", type=int)
    reject = sub.add_parser("reject", help="отклонить заказ")
    reject.add_argument("order_id", type=int)

    args = parser.parse_args()
    db = Storage(config.DB_PATH)

    if args.cmd == "keys":
        items = split_items(args.items)
        if not items:
            print("нет ключей")
            return 1
        db.add_keys(args.plan, items)
        print(f"добавлено {len(items)} ключей для {args.plan}")
    elif args.cmd == "list":
        for plan in config.PLANS:
            print(f"{plan['title']:12} {db.keys_left(plan['code'])} шт.")
    elif args.cmd == "orders":
        for r in db.recent_orders(20):
            print(f"#{r['id']:<4} {r['title']:14} {kb.money(r['price']):>10}  "
                  f"{r['status']:10} user {r['user_id']}")
    elif args.cmd == "stats":
        s = db.stats()
        print(f"Пользователи: {s['users']} | Подписки: {s['active_subs']} | "
              f"Выручка: {kb.money(s['revenue'])}")
    elif args.cmd == "confirm":
        from bot import VpnBot, Telegram

        bot = VpnBot(Telegram(config.BOT_TOKEN), db, config.ADMINS)
        bot.deliver(args.order_id)
        print("выполнено")
    elif args.cmd == "reject":
        order = db.order(args.order_id)
        if order:
            db.set_status(args.order_id, "rejected")
            print(f"заказ #{args.order_id} отклонён")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
