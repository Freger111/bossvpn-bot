"""Проверка ключей и сервера: трафик, имена, комментарии."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config  # noqa: E402
from core import server as server_mod  # noqa: E402
from core.storage import Storage  # noqa: E402


def get_panel():
    return server_mod.Panel(config.PANEL_URL, config.PANEL_USER, config.PANEL_PASS)


def cmd_traffic() -> int:
    panel = get_panel()
    for client in panel.list_clients():
        email = client.get("email") or ""
        traffic = panel.traffic(email)
        used = (traffic.get("up") or 0) + (traffic.get("down") or 0)
        comment = client.get("comment") or "—"
        print(f"{email:16} {server_mod.bytes_to_gb(used):>12}  {comment[:30]}")
    return 0


def cmd_rename(uuid: str, name: str) -> int:
    panel = get_panel()
    client = panel.find_by_uuid(uuid)
    if not client:
        print("клиент не найден")
        return 1
    ok = panel.update(client["email"], {"email": name})
    print("переименован" if ok else "не удалось")
    return 0 if ok else 1


def cmd_comment(uuid: str, text: str) -> int:
    panel = get_panel()
    client = panel.find_by_uuid(uuid)
    if not client:
        print("клиент не найден")
        return 1
    ok = panel.update(client["email"], {"comment": text})
    print("комментарий сохранён" if ok else "не удалось")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Ключи и трафик VPN")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("traffic", help="использование по всем ключам")
    rename = sub.add_parser("rename", help="переименовать ключ")
    rename.add_argument("uuid")
    rename.add_argument("name")
    comment = sub.add_parser("comment", help="задать описание ключа")
    comment.add_argument("uuid")
    comment.add_argument("text")

    args = parser.parse_args()
    if args.cmd == "traffic":
        return cmd_traffic()
    if args.cmd == "rename":
        return cmd_rename(args.uuid, args.name)
    if args.cmd == "comment":
        return cmd_comment(args.uuid, args.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
