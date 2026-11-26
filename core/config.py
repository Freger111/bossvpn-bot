"""Настройки VPN-бота."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # core/
BASE = ROOT.parent                              # корень проекта
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
DB_PATH = DATA / "vpn.db"


def load_env() -> None:
    env = BASE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

VERSION = "1.3"
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMINS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",")
          if x.strip().isdigit()}

BRAND = os.environ.get("BRAND", "БоссVPN")
SUPPORT = os.environ.get("SUPPORT", "@bossvphbot")
BOT_USER = os.environ.get("BOT_USERNAME", "bossVPHbot")
PAY_SBP = os.environ.get("PAY_SBP", "+7 900 000-00-00")
PAY_NAME = os.environ.get("PAY_NAME", "Т-Банк")
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "0"))   # 0 — без пробного периода
WINBACK_PERCENT = int(os.environ.get("WINBACK_PERCENT", "20"))   # 0 — не возвращать ушедших
WINBACK_AFTER_DAYS = int(os.environ.get("WINBACK_AFTER_DAYS", "1"))
REF_PERCENT = int(os.environ.get("REF_PERCENT", "10"))

PANEL_URL = os.environ.get("PANEL_URL", "")
PANEL_USER = os.environ.get("PANEL_USER", "admin")
PANEL_PASS = os.environ.get("PANEL_PASS", "")


def load_locations() -> list[dict]:
    """Локации (страны) серверов. У каждой — своя панель 3x-ui и свой пул ключей.

    LOCATIONS=de,fi
    LOC_FI_NAME=🇫🇮 Финляндия
    LOC_FI_PANEL_URL=... / LOC_FI_PANEL_USER=... / LOC_FI_PANEL_PASS=...
    Первая локация по умолчанию берёт PANEL_URL / PANEL_USER / PANEL_PASS.
    """
    names = {"de": "🇩🇪 Германия", "fi": "🇫🇮 Финляндия", "nl": "🇳🇱 Нидерланды"}
    codes = [c.strip().lower() for c in os.environ.get("LOCATIONS", "de").split(",")
             if c.strip()] or ["de"]
    result = []
    for i, code in enumerate(codes):
        env = lambda key, default="": os.environ.get(f"LOC_{code.upper()}_{key}", default)  # noqa: E731
        result.append({
            "code": code,
            "name": env("NAME", names.get(code, code.upper())),
            "url": env("PANEL_URL", PANEL_URL if i == 0 else ""),
            "user": env("PANEL_USER", PANEL_USER if i == 0 else "admin"),
            "pass": env("PANEL_PASS", PANEL_PASS if i == 0 else ""),
        })
    return result


LOCATIONS = load_locations()
DEFAULT_LOCATION = LOCATIONS[0]["code"]


def location(code: str) -> dict:
    return next((loc for loc in LOCATIONS if loc["code"] == code), LOCATIONS[0])

YOOKASSA_SHOP_ID = os.environ.get("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET = os.environ.get("YOOKASSA_SECRET", "")
LAVA_SHOP_ID = os.environ.get("LAVA_SHOP_ID", "")
LAVA_SECRET = os.environ.get("LAVA_SECRET", "")
ENOT_API_KEY = os.environ.get("ENOT_API_KEY", "")
ENOT_SHOP_ID = os.environ.get("ENOT_SHOP_ID", "")
REMIND_DAYS = int(os.environ.get("REMIND_DAYS", "3"))
LOW_KEYS = int(os.environ.get("LOW_KEYS", "3"))   # предупреждать админа, когда ключей ≤ N
REVIEW_AFTER_DAYS = int(os.environ.get("REVIEW_AFTER_DAYS", "3"))   # 0 — не спрашивать отзыв
REVIEWS_CHANNEL = os.environ.get("REVIEWS_CHANNEL", "")   # @канал для публикации отзывов

# Настройки, которые админ меняет прямо в боте (хранятся в БД и перекрывают .env)
EDITABLE = [
    ("TRIAL_DAYS", "🎁 Пробный период, дней", "0 — выключен"),
    ("WINBACK_PERCENT", "💙 Скидка ушедшим, %", "0 — не писать ушедшим"),
    ("WINBACK_AFTER_DAYS", "💙 Писать ушедшим через, дней", ""),
    ("REF_PERCENT", "👥 Бонус за друга, %", ""),
    ("REMIND_DAYS", "⏳ Напоминать до конца, дней", ""),
    ("REVIEW_AFTER_DAYS", "⭐ Просить отзыв через, дней", "0 — не просить"),
    ("LOW_KEYS", "🔑 Алерт, если ключей ≤", ""),
    ("REVIEWS_CHANNEL", "📢 Канал отзывов", "@канал, «-» — очистить"),
    ("PAY_SBP", "💳 Номер СБП", ""),
    ("PAY_NAME", "🏦 Банк", ""),
    ("SUPPORT", "💬 Поддержка", "@username"),
]
ENV_LOCATIONS = [dict(loc) for loc in LOCATIONS]


def set_value(key: str, raw: str) -> str:
    """Проверяет и применяет значение. Возвращает текст ошибки или пустую строку."""
    raw = raw.strip()
    if isinstance(globals()[key], int):
        if not raw.isdigit():
            return "Нужно целое число 0 или больше."
        value = int(raw)
        if key.endswith("PERCENT") and value > 100:
            return "Процент — от 0 до 100."
        globals()[key] = value
    else:
        if not raw:
            return "Пустое значение."
        globals()[key] = "" if raw == "-" else raw[:100]
    return ""


def set_locations(extra: list[dict]) -> None:
    """Локации из .env плюс добавленные в боте (по коду — бот важнее)."""
    merged = {loc["code"]: dict(loc) for loc in ENV_LOCATIONS}
    for loc in extra:
        merged[loc["code"]] = dict(loc)
    LOCATIONS[:] = list(merged.values())

BLACK = (8, 10, 16)
CYAN = (58, 215, 255)
WHITE = (245, 247, 252)
GREY = (140, 148, 175)

BANNER = BASE / "vpn_brand" / "banner_1280x640.png"
AVATAR = BASE / "vpn_brand" / "avatar_512.png"


def plan_image(code: str):
    return BASE / "vpn_brand" / f"plan_{code}.png"

PLANS = [
    {"code": "m1", "title": "1 месяц", "days": 30, "price": 99, "gb": 30,
     "devices": 4, "note": "30 ГБ · до 4 устройств"},
    {"code": "m3", "title": "3 месяца", "days": 90, "price": 199, "gb": 100,
     "devices": 6, "note": "100 ГБ · до 6 устройств"},
    {"code": "m6", "title": "6 месяцев", "days": 180, "price": 349, "gb": 200,
     "devices": 8, "note": "200 ГБ · до 8 устройств"},
    {"code": "y1", "title": "12 месяцев", "days": 365, "price": 599, "gb": 500,
     "devices": 10, "note": "500 ГБ · до 10 устройств"},
]
TRIAL_GB = 20
