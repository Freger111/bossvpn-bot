"""Кнопки и тексты VPN-бота."""
from __future__ import annotations

from . import config


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def per_month(plan: dict) -> int:
    return round(plan["price"] / max(1, plan["days"] / 30))


def days_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} день"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} дня"
    return f"{n} дней"


def main_menu(admin: bool = False, trial_days: int = 0) -> dict:
    rows = [
        [{"text": "🛡 Подключить VPN", "callback_data": "plans"}],
        [
            {"text": "🔑 Моя подписка", "callback_data": "my"},
            {"text": "📱 Как подключить", "callback_data": "help"},
        ],
        [
            {"text": "🎁 Бонусы за друзей", "callback_data": "invite"},
            {"text": "💬 Поддержка", "callback_data": "support"},
        ],
    ]
    if trial_days:
        rows.insert(1, [{"text": f"🎁 Попробовать бесплатно · {days_word(trial_days)}",
                         "callback_data": "trial"}])
    if admin:
        rows.append([{"text": "⚙️ Админ-панель", "callback_data": "adm"}])
    return {"inline_keyboard": rows}


PLAN_ICONS = {"m1": "🛡", "m3": "🚀", "m6": "💎", "y1": "👑"}


def plans() -> dict:
    rows = []
    for plan in config.PLANS:
        icon = PLAN_ICONS.get(plan["code"], "🛡")
        label = f"{icon} {plan['title']} — {money(plan['price'])}"
        if plan["days"] > 30:
            label += f" · {per_month(plan)} ₽/мес"
        rows.append([{"text": label, "callback_data": f"plan:{plan['code']}"}])
    rows.append([{"text": "🏷 Есть промокод", "callback_data": "promo"}])
    rows.append([{"text": "🏠 Главное меню", "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def discounted(price: int, percent: int) -> int:
    return price - price * percent // 100


def plan_card(plan_code: str, percent: int = 0) -> dict:
    plan = next((p for p in config.PLANS if p["code"] == plan_code), {})
    buy = (f"💳 Купить за {money(discounted(plan['price'], percent))}"
           if plan else "💳 Купить")
    return {"inline_keyboard": [
        [{"text": buy, "callback_data": f"buy:{plan_code}"}],
        [{"text": "← Все тарифы", "callback_data": "plans"}],
    ]}


def locations(plan_code: str, codes: list[str]) -> dict:
    rows = [[{"text": config.location(c)["name"], "callback_data": f"buy:{plan_code}:{c}"}]
            for c in codes]
    rows.append([{"text": "← Тариф", "callback_data": f"plan:{plan_code}"}])
    return {"inline_keyboard": rows}


def pay_manual(order_id: int) -> dict:
    return {"inline_keyboard": [
        [{"text": "✅ Я оплатил", "callback_data": f"paid:{order_id}"}],
        [{"text": "✖️ Отменить заказ", "callback_data": f"cancel:{order_id}"}],
    ]}


def sub_menu(active: bool) -> dict:
    first = "🔄 Продлить подписку" if active else "🛡 Выбрать тариф"
    return {"inline_keyboard": [
        [{"text": first, "callback_data": "plans"}],
        [{"text": "📱 Как подключить", "callback_data": "help"},
         {"text": "🏠 Меню", "callback_data": "menu"}],
    ]}


def admin_confirm(order_id: int) -> dict:
    return {"inline_keyboard": [[
        {"text": "✅ Выдать", "callback_data": f"ok:{order_id}"},
        {"text": "❌ Отклонить", "callback_data": f"no:{order_id}"},
    ]]}


def admin_panel() -> dict:
    return {"inline_keyboard": [
        [{"text": "🧾 Заказы", "callback_data": "adm:orders"}],
        [{"text": "📊 Статистика", "callback_data": "adm:stats"}],
        [
            {"text": "📈 Источники", "callback_data": "adm:sources"},
            {"text": "👥 Рефералы", "callback_data": "adm:refs"},
        ],
        [
            {"text": "🔑 Ключей в наличии", "callback_data": "adm:keys"},
            {"text": "⭐ Отзывы", "callback_data": "adm:reviews"},
        ],
        [{"text": "🏷 Промокоды", "callback_data": "adm:promos"}],
        [{"text": "🔄 Синхронизировать ключи с сервера", "callback_data": "adm:keysync"}],
        [{"text": "← Меню", "callback_data": "menu"}],
    ]}


def review_stars() -> dict:
    return {"inline_keyboard": [
        [{"text": "⭐" * n, "callback_data": f"rate:{n}"} for n in (5, 4, 3)],
        [{"text": "⭐" * n, "callback_data": f"rate:{n}"} for n in (2, 1)],
    ]}


def stars(rating: int) -> str:
    return "⭐" * rating + "☆" * (5 - rating)


def back(to: str = "menu", label: str = "← Назад") -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": to}]]}


HELP = (
    "📱 <b>Как подключить {brand}</b>\n\n"
    "<b>1.</b> Установите приложение:\n"
    "· <b>iPhone / iPad</b> — Happ или V2RayTun (App Store)\n"
    "· <b>Android</b> — Happ или v2rayNG (Google Play)\n"
    "· <b>Windows</b> — Hiddify или v2rayN\n\n"
    "<b>2.</b> Откройте «🔑 Моя подписка» и нажмите на ключ — он скопируется.\n\n"
    "<b>3.</b> В приложении нажмите «+» → «Импорт из буфера» и включите VPN.\n\n"
    "Готово! Если что-то не получается — напишите в поддержку, поможем 🙌"
)

SHORT_DESCRIPTION = "Быстрый VPN без логов. Подключение за 2 минуты, ключ сразу в чат. iOS · Android · Windows"

DESCRIPTION = (
    "🛡 {brand} — быстрый и стабильный VPN без логов.\n\n"
    "⚡ Подключение за 2 минуты\n"
    "📱 iOS, Android и Windows\n"
    "🔒 Протокол VLESS · Reality\n"
    "💳 Оплата по СБП или картой — ключ приходит прямо в чат\n"
    "🎁 Бонусы за приглашённых друзей\n\n"
    "Нажмите «Запустить», чтобы выбрать тариф 👇"
)

COMMANDS = [
    {"command": "start", "description": "Главное меню и тарифы"},
    {"command": "my", "description": "Моя подписка и ключ"},
    {"command": "help", "description": "Как подключить VPN"},
]
