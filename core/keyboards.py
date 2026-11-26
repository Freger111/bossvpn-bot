"""Кнопки и тексты VPN-бота."""
from __future__ import annotations

from . import config


def money(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def main_menu(admin: bool = False) -> dict:
    rows = [
        [{"text": "🛡 Купить VPN", "callback_data": "plans"}],
        [
            {"text": "🔑 Моя подписка", "callback_data": "my"},
            {"text": "📱 Инструкции", "callback_data": "help"},
        ],
        [
            {"text": "💬 Поддержка", "callback_data": "support"},
            {"text": "🎁 Пригласить друга", "callback_data": "invite"},
        ],
    ]
    if admin:
        rows.append([{"text": "⚙️ Админ-панель", "callback_data": "adm"}])
    return {"inline_keyboard": rows}


def plans() -> dict:
    icons = {"m1": "🛡", "m3": "🚀", "m6": "💎", "y1": "👑"}
    rows = []
    for plan in config.PLANS:
        icon = icons.get(plan["code"], "🛡")
        rows.append([{"text": f"{icon} {plan['title']} — {money(plan['price'])}"
                              f" · {plan.get('gb', 0)} ГБ",
                      "callback_data": f"plan:{plan['code']}"}])
    rows.append([{"text": "◀️ Меню", "callback_data": "menu"}])
    return {"inline_keyboard": rows}


def plan_card(plan_code: str) -> dict:
    rows = [[{"text": "💳 Оплатить", "callback_data": f"buy:{plan_code}"},
             {"text": "← Тарифы", "callback_data": "plans"}]]
    return {"inline_keyboard": rows}


def pay_manual(order_id: int) -> dict:
    return {"inline_keyboard": [
        [{"text": "✅ Я оплатил", "callback_data": f"paid:{order_id}"}],
        [{"text": "← Отменить", "callback_data": f"cancel:{order_id}"}],
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
        [{"text": "🔑 Ключей в наличии", "callback_data": "adm:keys"}],
        [{"text": "🔄 Синхронизировать ключи с сервера", "callback_data": "adm:keysync"}],
        [{"text": "← Меню", "callback_data": "menu"}],
    ]}


def back(to: str = "menu", label: str = "← Назад") -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": to}]]}


HELP = (
    "📱 <b>Как подключить {brand}</b>\n\n"
    "<b>iOS</b>: App Store → «V2RayTun» или «Shadowrocket» → импорт ключа.\n"
    "<b>Android</b>: Google Play → «v2rayNG» → «+» → импорт из буфера.\n"
    "<b>Windows</b>: скачайте «v2rayN», вставьте ключ → подключить.\n\n"
    "Ключ придёт автоматически после оплаты. Просто скопируйте его в приложение."
)
