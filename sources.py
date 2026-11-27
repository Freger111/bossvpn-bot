"""Источники трафика и рефералы."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config  # noqa: E402
from core.storage import Storage  # noqa: E402


def main() -> int:
    db = Storage(config.DB_PATH)
    print("=== Источники трафика ===")
    for r in db.stats_by_source():
        print(f"{r['source'] or 'прямой вход':20} {r['count']}")
    print("\n=== Топ приглашающих ===")
    for r in db.top_referrers(10):
        name = r["username"] or f"id{r['id']}"
        print(f"@{name:24} {r['invites']} пригл. · бонус {r['balance']} ₽")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
