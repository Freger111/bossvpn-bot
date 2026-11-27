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
REF_PERCENT = int(os.environ.get("REF_PERCENT", "10"))

PANEL_URL = os.environ.get("PANEL_URL", "")
PANEL_USER = os.environ.get("PANEL_USER", "admin")
PANEL_PASS = os.environ.get("PANEL_PASS", "")

# прокси подписок через домен бота (bothost и т.п.)
SUB_PORT = int(os.environ.get("SUB_PORT", os.environ.get("PORT", "0")) or 0)
SUB_UPSTREAM = os.environ.get("SUB_UPSTREAM", "http://31.76.45.106/u4r1ak8wekd7wyrv")

YOOKASSA_SHOP_ID = os.environ.get("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET = os.environ.get("YOOKASSA_SECRET", "")
LAVA_SHOP_ID = os.environ.get("LAVA_SHOP_ID", "")
LAVA_SECRET = os.environ.get("LAVA_SECRET", "")
ENOT_API_KEY = os.environ.get("ENOT_API_KEY", "")
ENOT_SHOP_ID = os.environ.get("ENOT_SHOP_ID", "")
REMIND_DAYS = int(os.environ.get("REMIND_DAYS", "3"))

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
