"""VPN-бот: покупка тарифа, оплата, выдача ключа, подписка, админка."""
from __future__ import annotations

import html
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config, keyboards as kb  # noqa: E402
from core import payments as pay_mod  # noqa: E402
from core import server as server_mod  # noqa: E402
from core.storage import Storage  # noqa: E402


# ---------------------------------------------------------------- клиент Telegram
def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    boundary = "----vpn" + uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"'
                     f"\r\n\r\n{value}\r\n".encode("utf-8"))
    for key, (filename, data, mime) in files.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"; '
                     f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode("utf-8"))
        parts.append(data)
        parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class Telegram:
    def __init__(self, token: str, transport=None):
        self.token = token
        self.transport = transport
        self.base = f"https://api.telegram.org/bot{token}"

    def call(self, method: str, files: dict | None = None, **params) -> dict:
        if self.transport is not None:
            return self.transport(method, params, files)
        params = {k: v for k, v in params.items() if v is not None}
        url = f"{self.base}/{method}"
        last = None
        for attempt in range(3):
            try:
                if files:
                    body, ctype = _multipart(params, files)
                    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
                else:
                    req = urllib.request.Request(
                        url, data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
                        headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, ssl.SSLError, TimeoutError, ConnectionError) as exc:
                last = exc
                time.sleep(1 + attempt)
        raise last if last else RuntimeError("telegram call failed")


# ---------------------------------------------------------------- бот
class VpnBot:
    def __init__(self, tg: Telegram, db: Storage, admins: set[int]):
        self.tg = tg
        self.db = db
        self.admins = admins
        self.offset = 0
        self.username = ""
        self.awaiting_key: dict[int, dict] = {}
        self.awaiting_review: dict[int, int] = {}
        self.awaiting_promo: set[int] = set()
        self.panels: dict[str, server_mod.Panel] = {}
        self._last_card_check = 0.0
        self._last_remind = 0.0
        self._last_health = 0.0
        self._alerts: set[str] = set()
        for loc in config.LOCATIONS:
            if not loc["url"]:
                continue
            try:
                self.panels[loc["code"]] = server_mod.Panel(loc["url"], loc["user"], loc["pass"])
            except Exception as exc:
                print(f"панель {loc['code']} недоступна:", exc)

    @property
    def panel(self):
        return self.panels.get(config.DEFAULT_LOCATION)

    def panel_for(self, payload: str):
        """Панель сервера, которому принадлежит ключ."""
        return self.panels.get(self.db.key_location(payload))

    def setup_profile(self) -> None:
        """Описание, короткое описание и меню команд бота в Telegram."""
        for method, params in (
                ("setMyCommands", {"commands": kb.COMMANDS}),
                ("setMyDescription", {"description": kb.DESCRIPTION.format(brand=config.BRAND)}),
                ("setMyShortDescription", {"short_description": kb.SHORT_DESCRIPTION})):
            try:
                self.tg.call(method, **params)
            except Exception as exc:
                print(f"{method}:", exc)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admins

    # ---------- отправка ----------
    def say(self, chat_id: int, text: str, markup: dict | None = None) -> dict:
        return self.tg.call("sendMessage", chat_id=chat_id, text=text[:4000],
                            parse_mode="HTML", reply_markup=markup)

    def say_photo(self, chat_id: int, path: Path, caption: str, markup: dict) -> None:
        if path.exists():
            try:
                result = self.tg.call(
                    "sendPhoto",
                    files={"photo": (path.name, path.read_bytes(), "image/png")},
                    chat_id=chat_id, caption=caption[:1000], parse_mode="HTML",
                    reply_markup=markup)
                if result.get("ok"):
                    return
            except Exception:
                pass
        self.say(chat_id, caption, markup)

    def send_banner(self, chat_id: int, caption: str, markup: dict) -> None:
        if config.BANNER.exists():
            result = self.tg.call("sendPhoto",
                                  files={"photo": ("banner.png",
                                                   config.BANNER.read_bytes(),
                                                   "image/png")},
                                  chat_id=chat_id, caption=caption[:1000],
                                  parse_mode="HTML", reply_markup=markup)
            if result.get("ok"):
                return
        self.say(chat_id, caption, markup)

    # ---------- витрина ----------
    def welcome(self, chat_id: int, user_id: int, username: str = "",
                ref_id: int | None = None, source: str = "") -> None:
        self.db.ensure_user(user_id, username, ref_id, source)
        from_price = min(kb.per_month(p) for p in config.PLANS)
        caption = (f"🛡 <b>{config.BRAND}</b> — быстрый VPN без логов\n\n"
                   f"⚡ Подключение за 2 минуты\n"
                   f"📱 iOS · Android · Windows\n"
                   f"🔒 VLESS · Reality — стабильно и незаметно\n"
                   f"💳 СБП или карта — ключ приходит прямо в чат\n\n"
                   f"Тарифы от <b>{from_price} ₽/мес</b> 👇")
        self.send_banner(chat_id, caption, self.menu(user_id))

    def menu(self, user_id: int) -> dict:
        trial = config.TRIAL_DAYS if self.trial_available(user_id) else 0
        return kb.main_menu(self.is_admin(user_id), trial)

    def show_plans(self, chat_id: int, user_id: int = 0) -> None:
        text = ("🛡 <b>Выберите тариф</b>\n\n"
                "Чем дольше срок — тем дешевле месяц.\n"
                "Во всех тарифах: без логов · VLESS · Reality · iOS / Android / Windows")
        code, percent = self.user_promo(user_id)
        if percent:
            text += f"\n\n🏷 Промокод <b>{code}</b>: скидка {percent}% на покупку"
        self.say(chat_id, text, kb.plans())

    def show_plan(self, chat_id: int, plan_code: str, user_id: int = 0) -> None:
        plan = next((p for p in config.PLANS if p["code"] == plan_code), None)
        if plan is None:
            return
        left = self.db.keys_left(plan_code)
        icon = kb.PLAN_ICONS.get(plan_code, "🛡")
        places = " · ".join(loc["name"] for loc in config.LOCATIONS)
        text = (f"{icon} <b>{plan['title']}</b> · {kb.money(plan['price'])}\n\n"
                f"📅 {plan['days']} дней доступа\n"
                f"📦 {plan.get('gb', 0)} ГБ трафика\n"
                f"📱 до {plan.get('devices', 1)} устройств\n"
                f"🌍 {places}\n"
                f"⚡ VLESS · Reality\n\n"
                f"💡 Выходит ≈ <b>{kb.per_month(plan)} ₽ в месяц</b>")
        code, percent = self.user_promo(user_id)
        if percent:
            text += (f"\n\n🏷 С промокодом {code}: "
                     f"<b>{kb.money(kb.discounted(plan['price'], percent))}</b>")
        if left == 0:
            text += "\n\n⏳ Ключи временно закончились — скоро пополним."
        elif left <= 5:
            text += f"\n\n🔥 Осталось ключей: {left}"
        self.say_photo(chat_id, config.plan_image(plan_code), text,
                       kb.plan_card(plan_code, percent))

    # ---------- покупка ----------
    def start_purchase(self, chat_id: int, user_id: int, plan_code: str,
                       location: str = "") -> None:
        plan = next((p for p in config.PLANS if p["code"] == plan_code), None)
        if plan is None:
            return
        if location not in {loc["code"] for loc in config.LOCATIONS}:
            location = ""
        if not location:
            available = [loc["code"] for loc in config.LOCATIONS
                         if self.db.keys_left(plan_code, loc["code"])]
            if len(available) > 1:
                self.say(chat_id, f"🌍 <b>Выберите страну сервера</b>\n\n"
                                  f"Тариф: {plan['title']} · {kb.money(plan['price'])}\n"
                                  f"Чем ближе сервер — тем выше скорость.",
                         kb.locations(plan_code, available))
                return
            location = available[0] if available else ""
        user = self.db.ensure_user(user_id)
        promo, percent = self.user_promo(user_id)
        full = kb.discounted(plan["price"], percent)
        balance = user.get("balance") or 0
        balance_used = min(balance, full)
        price = full - balance_used
        order_id = self.db.create_order(user_id, plan, price=price, balance_used=balance_used,
                                        location=location, promo=promo if percent else "")
        if balance_used:
            self.db.add_balance(user_id, -balance_used)
        if price == 0:
            self.db.set_status(order_id, "awaiting")
            self.deliver(order_id)
            return
        text = f"🧾 <b>Заказ #{order_id}</b> · {plan['title']}\n\n"
        if location and len(config.LOCATIONS) > 1:
            text += f"Сервер: {config.location(location)['name']}\n"
        text += f"К оплате: <b>{kb.money(price)}</b>"
        if percent:
            text += f"\n🏷 Промокод {promo}: −{percent}%"
        if balance_used:
            text += f"\n🎁 Бонусами списано: {kb.money(balance_used)}"
        text += (f"\n\n<b>Оплата по СБП</b>\n"
                 f"Номер: <code>{config.PAY_SBP}</code>\n"
                 f"Банк: {config.PAY_NAME}\n\n"
                 f"После перевода нажмите «✅ Я оплатил» — ключ придёт в этот чат.")

        markup = kb.pay_manual(order_id)
        if config.YOOKASSA_SECRET:
            markup["inline_keyboard"].insert(0, [
                {"text": "💳 Оплатить картой (ЮKassa)",
                 "callback_data": f"card:{order_id}"}])
        if config.LAVA_SECRET:
            markup["inline_keyboard"].insert(0, [
                {"text": "💳 Оплатить картой (Lava)",
                 "callback_data": f"lava:{order_id}"}])
        if config.ENOT_API_KEY:
            markup["inline_keyboard"].insert(0, [
                {"text": "💳 Оплатить картой",
                 "callback_data": f"enot:{order_id}"}])
        self.say(chat_id, text, markup)

    def cmd_enot_payment(self, chat_id: int, user_id: int, order_id: int) -> None:
        order = self.db.order(order_id)
        if not order or order["user_id"] != user_id:
            return
        if order["status"] != "new":
            self.say(chat_id, "✅ Этот заказ уже обработан.")
            return
        url = pay_mod.enot_create_invoice(config.ENOT_API_KEY, config.ENOT_SHOP_ID,
                                          order["price"], order_id)
        if not url:
            self.say(chat_id, "😕 Платёжный сервис не ответил. Попробуйте ещё раз или оплатите по СБП.",
                     kb.pay_manual(order_id))
            return
        self.db.set_charge(order_id, "enot:" + str(order_id))
        self.db.set_status(order_id, "card_pending")
        self.say(chat_id,
                 f"💳 <b>Оплата картой</b>\n\nК оплате: <b>{kb.money(order['price'])}</b>\n\n"
                 f"1. Нажмите «Перейти к оплате»\n"
                 f"2. Оплатите и вернитесь в бот\n"
                 f"3. Нажмите «Проверить оплату» — ключ придёт сразу",
                 {"inline_keyboard": [
                     [{"text": "💳 Перейти к оплате", "url": url}],
                     [{"text": "🔄 Проверить оплату",
                       "callback_data": f"checkpay:{order_id}"}],
                 ]})

    def cmd_lava_payment(self, chat_id: int, user_id: int, order_id: int) -> None:
        order = self.db.order(order_id)
        if not order or order["user_id"] != user_id:
            return
        if order["status"] != "new":
            self.say(chat_id, "✅ Этот заказ уже обработан.")
            return
        url = pay_mod.lava_create_invoice(config.LAVA_SHOP_ID, config.LAVA_SECRET,
                                          order["price"], order_id)
        if not url:
            self.say(chat_id, "😕 Платёжный сервис не ответил. Попробуйте ещё раз или оплатите по СБП.",
                     kb.pay_manual(order_id))
            return
        self.db.set_charge(order_id, "lava")
        self.db.set_status(order_id, "card_pending")
        self.say(chat_id,
                 f"💳 <b>Оплата картой</b>\n\nК оплате: <b>{kb.money(order['price'])}</b>\n\n"
                 f"1. Нажмите «Перейти к оплате»\n"
                 f"2. Оплатите и вернитесь в бот\n"
                 f"3. Нажмите «Проверить оплату» — ключ придёт сразу",
                 {"inline_keyboard": [
                     [{"text": "💳 Перейти к оплате", "url": url}],
                     [{"text": "🔄 Проверить оплату",
                       "callback_data": f"checkpay:{order_id}"}],
                 ]})

    def cmd_card_payment(self, chat_id: int, user_id: int, order_id: int) -> None:
        order = self.db.order(order_id)
        if not order or order["user_id"] != user_id:
            return
        if order["status"] != "new":
            self.say(chat_id, "✅ Этот заказ уже обработан.")
            return
        result = pay_mod.create_payment(config.YOOKASSA_SHOP_ID, config.YOOKASSA_SECRET,
                                        order["price"], f"{config.BRAND} · {order['title']}",
                                        order_id)
        url = (result.get("confirmation") or {}).get("confirmation_url")
        pay_id = result.get("id")
        if not url or not pay_id:
            self.say(chat_id, "😕 Платёжный сервис не ответил. Попробуйте ещё раз или оплатите по СБП.",
                     kb.pay_manual(order_id))
            return
        self.db.set_charge(order_id, pay_id)
        self.db.set_status(order_id, "card_pending")
        self.say(chat_id,
                 f"💳 <b>Оплата картой</b>\n\nК оплате: <b>{kb.money(order['price'])}</b>\n\n"
                 f"1. Нажмите «Перейти к оплате»\n"
                 f"2. Оплатите и вернитесь в бот\n"
                 f"3. Нажмите «Проверить оплату» — ключ придёт сразу",
                 {"inline_keyboard": [
                     [{"text": "💳 Перейти к оплате", "url": url}],
                     [{"text": "🔄 Проверить оплату",
                       "callback_data": f"checkpay:{order_id}"}],
                 ]})

    def check_card_payment(self, chat_id: int, order_id: int) -> None:
        order = self.db.order(order_id)
        if not order or not order.get("charge_id"):
            self.say(chat_id, "Платёж не найден. Создайте заказ заново в разделе тарифов.")
            return
        charge = order["charge_id"]
        if charge.startswith("enot:"):
            status = pay_mod.enot_status(config.ENOT_API_KEY, config.ENOT_SHOP_ID,
                                         str(order_id))
            if status == "paid":
                self.db.set_status(order_id, "awaiting")
                self.deliver(order_id)
                self.say(chat_id, "✅ Оплата получена! Ключ уже в чате.")
            elif status in ("expired", "fail", "rejected"):
                self.db.set_status(order_id, "new")
                self.say(chat_id, "❌ Платёж отменён. Можно попробовать ещё раз или оплатить по СБП.")
            else:
                self.say(chat_id, "⏳ Платёж пока не поступил. Обычно это занимает до минуты — проверьте чуть позже.")
            return
        if charge == "lava":
            status = pay_mod.lava_status(config.LAVA_SHOP_ID, config.LAVA_SECRET, order_id)
            if status == "success":
                self.db.set_status(order_id, "awaiting")
                self.deliver(order_id)
                self.say(chat_id, "✅ Оплата получена! Ключ уже в чате.")
            elif status == "fail":
                self.db.set_status(order_id, "new")
                self.say(chat_id, "❌ Платёж отменён. Можно попробовать ещё раз или оплатить по СБП.")
            else:
                self.say(chat_id, "⏳ Платёж пока не поступил. Обычно это занимает до минуты — проверьте чуть позже.")
            return
        payment = pay_mod.get_payment(config.YOOKASSA_SHOP_ID, config.YOOKASSA_SECRET,
                                      charge[3:] if charge.startswith("yk:") else charge)
        status = pay_mod.status(payment)
        if status == "succeeded":
            self.db.set_status(order_id, "awaiting")
            self.deliver(order_id)
            self.say(chat_id, "✅ Оплата получена! Ключ уже в чате.")
        elif status == "canceled":
            self.db.set_status(order_id, "new")
            self.say(chat_id, "❌ Платёж отменён. Можно попробовать ещё раз или оплатить по СБП.")
        else:
            self.say(chat_id, "⏳ Платёж пока не поступил. Обычно это занимает до минуты — проверьте чуть позже.")

    def mark_paid(self, chat_id: int, user_id: int, order_id: int) -> None:
        order = self.db.order(order_id)
        if not order or order["user_id"] != user_id:
            return
        if order["status"] != "new":
            self.say(chat_id, "✅ Этот заказ уже обработан.")
            return
        self.db.set_status(order_id, "awaiting")
        self.say(chat_id, "⏳ <b>Проверяем оплату</b>\n\n"
                          "Обычно это занимает несколько минут. Как только платёж "
                          "подтвердится, ключ придёт в этот чат.")
        for admin in self.admins:
            try:
                self.say(admin,
                         f"🔔 <b>Новая оплата</b>\n\nЗаказ #{order_id}\n"
                         f"Тариф: {order['title']}\n"
                         f"Сумма: {kb.money(order['price'])}\n"
                         f"Покупатель: <code>{user_id}</code>",
                         kb.admin_confirm(order_id))
            except Exception:
                pass

    def cancel_order(self, chat_id: int, user_id: int, order_id: int) -> None:
        order = self.db.order(order_id)
        if order and order["user_id"] == user_id and order["status"] == "new":
            self.db.set_status(order_id, "canceled")
            self.say(chat_id, "Заказ отменён. Возвращайтесь, когда будете готовы 🙌",
                     kb.back("plans", "🛡 Тарифы"))
        else:
            self.say(chat_id, "Этот заказ уже нельзя отменить.")

    def sync_server_sub(self, payload: str, expires_at: int,
                        rename_to: str = "", comment: str = "",
                        total_gb: int = 0, limit_ip: int = 0) -> tuple[str, str]:
        """Ставит срок, трафик, лимит устройств, имя на сервере и возвращает Happ-ссылку."""
        happ, email = "", ""
        panel = self.panel_for(payload)
        if not panel:
            return happ, email
        uuid = server_mod.uuid_from_payload(payload)
        if not uuid:
            return happ, email
        try:
            client = panel.find_by_uuid(uuid)
            if client:
                email = client.get("email") or ""
                fields = {"email": email, "enable": True}   # enable обязательно, иначе отключится
                if (client.get("expiryTime") or 0) != expires_at * 1000:
                    fields["expiryTime"] = expires_at * 1000
                if total_gb and (client.get("totalGB") or 0) != total_gb:
                    fields["totalGB"] = total_gb
                if limit_ip and (client.get("limitIp") or 0) != limit_ip:
                    fields["limitIp"] = limit_ip
                if rename_to:
                    new_email = "".join(
                        ch for ch in rename_to if ch.isalnum() or ch in "_@-")[:24] \
                        or f"client{uuid[:6]}"
                    taken = any(c["email"] == new_email and c["uuid"] != uuid
                                for c in panel.list_clients())
                    if taken:
                        new_email += f"-{uuid[:6]}"
                    fields["email"] = new_email
                    email = new_email
                if comment and (client.get("comment") or "") != comment:
                    fields["comment"] = comment
                if len(fields) > 1 or fields.get("email") != client.get("email"):
                    panel.update(client.get("email") or "", fields)
                happ = panel.happ_link(client["id"])
        except Exception as exc:
            print("sync_server_sub:", exc)
        return happ, email

    def deliver(self, order_id: int) -> None:
        order = self.db.order(order_id)
        if not order or order["status"] != "awaiting":
            return
        key = self.db.take_key(order["plan_code"], order_id, order.get("location") or "")
        if key is None:
            self.say(order["user_id"],
                     "⚠️ Ключи для этого тарифа временно закончились. Оплата сохранена — "
                     f"пришлём ключ в ближайшее время. Вопросы: {config.SUPPORT}")
            return
        self.db.set_status(order_id, "paid")
        if order.get("promo"):
            self.db.use_promo(order["promo"], order["user_id"])
        expires = self.db.grant(order["user_id"], order["days"], key)
        # реферальное вознаграждение 15% от фактически оплаченной суммы
        buyer = self.db.user(order["user_id"])
        ref_id = buyer.get("ref_id")
        if ref_id and ref_id != order["user_id"]:
            bonus = int(order["price"] * config.REF_PERCENT / 100)
            if bonus > 0:
                self.db.add_balance(ref_id, bonus)
        plan = next((p for p in config.PLANS if p["code"] == order["plan_code"]), {})
        buyer_name = buyer.get("username") or f"client{order['user_id']}"
        happ, server_name = self.sync_server_sub(
            key, expires,
            rename_to=buyer_name,
            comment=f"Заказ #{order_id} · {order['title']}",
            total_gb=plan.get("gb", 0),
            limit_ip=plan.get("devices", 0))
        self.say(order["user_id"],
                 self.key_text("🎉 <b>Готово! VPN активирован</b>", order["title"], expires,
                               plan.get("gb", 0), plan.get("devices", 1), key, happ),
                 kb.back("help", "📱 Как подключить"))

    @staticmethod
    def key_text(head: str, title: str, expires: int, gb: int, devices: int,
                 key: str, happ: str) -> str:
        lines = [f"{head}\n\n"
                 f"📦 Тариф: {title}\n"
                 f"📅 Действует до: <b>{time.strftime('%d.%m.%Y', time.localtime(expires))}</b>\n"
                 f"📊 Трафик: <b>{gb} ГБ</b>\n"
                 f"📱 Устройств: <b>{devices}</b>\n\n"
                 f"🔑 <b>Ваш ключ</b> — нажмите, чтобы скопировать:\n"
                 f"<code>{key}</code>"]
        if happ:
            lines.append(f"\n📲 <b>Happ</b> — подключение в один клик, "
                         f"там видна подписка и трафик:\n<code>{happ}</code>")
        lines.append("\nВставьте ключ в приложение — пошаговая инструкция по кнопке ниже.")
        return "\n".join(lines)

    # ---------- пробный период ----------
    def trial_available(self, user_id: int) -> bool:
        if config.TRIAL_DAYS <= 0 or not user_id:
            return False
        user = self.db.user(user_id)
        return bool(user) and not user.get("trial_used") and not self.db.sub(user_id) \
            and not self.db.has_paid(user_id)

    def start_trial(self, chat_id: int, user_id: int, frm: dict) -> None:
        if not self.trial_available(user_id):
            self.say(chat_id, "🎁 Пробный период уже использован. Выберите тариф — "
                              "от 49 ₽ в месяц.", kb.back("plans", "🛡 Тарифы"))
            return
        plan = config.PLANS[0]
        location = next((loc["code"] for loc in config.LOCATIONS
                         if self.db.keys_left(plan["code"], loc["code"])), "")
        if not location:
            self.say(chat_id, "⏳ Пробные ключи временно закончились — скоро пополним. "
                              "А пока можно выбрать тариф.", kb.back("plans", "🛡 Тарифы"))
            return
        trial = {"code": plan["code"], "title": "Пробный период",
                 "days": config.TRIAL_DAYS, "price": 0}
        order_id = self.db.create_order(user_id, trial, location=location)
        key = self.db.take_key(plan["code"], order_id, location)
        if key is None:
            self.db.set_status(order_id, "canceled")
            return
        self.db.set_status(order_id, "trial")
        self.db.set_trial_used(user_id)
        expires = self.db.grant(user_id, config.TRIAL_DAYS, key)
        happ, _ = self.sync_server_sub(
            key, expires, rename_to=frm.get("username") or f"client{user_id}",
            comment="Пробный период", total_gb=config.TRIAL_GB, limit_ip=1)
        self.say(chat_id,
                 self.key_text(f"🎁 <b>Пробный период на {kb.days_word(config.TRIAL_DAYS)}"
                               f" активирован</b>", "Пробный", expires,
                               config.TRIAL_GB, 1, key, happ),
                 kb.back("help", "📱 Как подключить"))

    # ---------- промокоды ----------
    @staticmethod
    def norm_code(code: str) -> str:
        return "".join(ch for ch in code.upper() if ch.isalnum() or ch == "_")[:32]

    def promo_error(self, code: str, user_id: int) -> str:
        promo = self.db.promo(code)
        if not promo:
            return "Такого промокода нет. Проверьте написание."
        if promo["max_uses"] and promo["used"] >= promo["max_uses"]:
            return "Этот промокод закончился."
        if self.db.promo_used_by(code, user_id):
            return "Вы уже использовали этот промокод."
        return ""

    def user_promo(self, user_id: int) -> tuple[str, int]:
        if not user_id:
            return "", 0
        code = self.db.user(user_id).get("promo") or ""
        if not code or self.promo_error(code, user_id):
            return "", 0
        return code, int(self.db.promo(code)["percent"])

    def apply_promo(self, chat_id: int, user_id: int, raw: str) -> None:
        code = self.norm_code(raw)
        error = self.promo_error(code, user_id) if code else "Промокод пустой."
        if error:
            self.say(chat_id, f"❌ {error}", kb.back("plans", "🛡 Тарифы"))
            return
        self.db.set_user_promo(user_id, code)
        self.say(chat_id, f"✅ Промокод <b>{code}</b> применён: скидка "
                          f"<b>{self.db.promo(code)['percent']}%</b> на покупку.",
                 kb.back("plans", "🛡 Выбрать тариф"))

    def admin_promo(self, chat_id: int, text: str) -> None:
        parts = text.split()
        if parts[0] == "/delpromo" and len(parts) == 2:
            code = self.norm_code(parts[1])
            done = self.db.delete_promo(code)
            self.say(chat_id, f"🗑 Промокод {code} удалён." if done else "Нет такого промокода.")
            return
        if parts[0] == "/newpromo" and len(parts) in (3, 4) \
                and all(x.isdigit() for x in parts[2:]) and 1 <= int(parts[2]) <= 100:
            code = self.norm_code(parts[1])
            limit = int(parts[3]) if len(parts) == 4 else 0
            self.db.save_promo(code, int(parts[2]), limit)
            link = f"https://t.me/{config.BOT_USER}?start=promo_{code}"
            self.say(chat_id, f"✅ Промокод <b>{code}</b>: −{parts[2]}%, "
                              f"{'до ' + str(limit) + ' активаций' if limit else 'без лимита'}.\n\n"
                              f"Ссылка, которая сразу применит код:\n<code>{link}</code>")
            return
        self.say(chat_id, "Формат:\n<code>/newpromo КОД ПРОЦЕНТ [ЛИМИТ]</code>\n"
                          "<code>/delpromo КОД</code>")

    # ---------- возврат ушедших ----------
    def send_winbacks(self) -> None:
        if config.WINBACK_PERCENT <= 0:
            return
        code = f"BACK{config.WINBACK_PERCENT}"
        if not self.db.promo(code):
            self.db.save_promo(code, config.WINBACK_PERCENT)
        for sub in self.db.winback_candidates(config.WINBACK_AFTER_DAYS):
            user_id = sub["user_id"]
            self.db.set_winback(user_id, sub["expires_at"])
            head = ("🎁 <b>Пробный период закончился</b>" if not self.db.has_paid(user_id)
                    else "💙 <b>Скучаем!</b> Ваша подписка закончилась")
            text = f"{head}\n\n"
            if not self.promo_error(code, user_id) and not self.user_promo(user_id)[1]:
                self.db.set_user_promo(user_id, code)
                text += (f"Дарим скидку <b>{config.WINBACK_PERCENT}%</b> на любой тариф — "
                         f"она уже применена, просто выберите срок 👇")
            else:
                text += "Возвращайтесь — ключ придёт сразу после оплаты 👇"
            try:
                self.say(user_id, text, kb.back("plans", "🛡 Выбрать тариф"))
            except Exception as exc:
                print("winback:", exc)

    # ---------- подписка ----------
    def show_sub(self, chat_id: int, user_id: int) -> None:
        sub = self.db.sub(user_id)
        if not sub:
            self.say(chat_id, "🔑 У вас пока нет подписки.\n\n"
                              "Выберите тариф — подключение займёт 2 минуты 👇",
                     kb.sub_menu(False))
            return
        now = int(time.time())
        if sub["expires_at"] <= now:
            self.say(chat_id, "⌛ Подписка закончилась.\n\nПродлите, чтобы снова пользоваться VPN 👇",
                     kb.sub_menu(False))
            return
        days_left = (sub["expires_at"] - now) // 86400 + 1
        lines = [f"🔑 <b>Моя подписка</b>\n\n"
                 f"✅ Активна · осталось <b>{days_left} дн.</b>\n"
                 f"📅 До: {time.strftime('%d.%m.%Y', time.localtime(sub['expires_at']))}"]
        balance = self.db.user(user_id).get("balance") or 0
        if balance:
            lines.append(f"🎁 Бонусный баланс: <b>{kb.money(balance)}</b> "
                         f"(спишется при следующей покупке)")
        if len(config.LOCATIONS) > 1:
            lines.append(f"🌍 Сервер: {config.location(self.db.key_location(sub['payload']))['name']}")
        key_uuid = server_mod.uuid_from_payload(sub["payload"])
        panel = self.panel_for(sub["payload"])
        if key_uuid and panel:
            try:
                client = panel.find_by_uuid(key_uuid)
                if client:
                    traffic = panel.traffic(client.get("email") or "")
                    used_bytes = (traffic.get("up") or 0) + (traffic.get("down") or 0)
                    used_gb = used_bytes / 1024 ** 3
                    total_gb = client.get("totalGB") or 0
                    lines.append(f"📊 Израсходовано: <b>{used_gb:.2f} ГБ</b>")
                    if total_gb:
                        left_gb = max(0.0, total_gb - used_gb)
                        lines.append(f"📦 Осталось: <b>{left_gb:.1f} ГБ из {total_gb} ГБ</b>")
                        if used_gb >= total_gb:
                            lines.append("⚠️ <b>Лимит трафика исчерпан</b> — доступ приостановлен.")
                    if client.get("comment"):
                        lines.append(f"Описание: {client['comment']}")
            except Exception:
                pass
        happ, _ = self.sync_server_sub(sub["payload"], sub["expires_at"])
        if happ:
            lines.append(f"\n📲 Happ (подписка и трафик видны в приложении):\n<code>{happ}</code>")
        lines.append(f"\n🔑 Ключ (нажмите, чтобы скопировать):\n<code>{sub['payload']}</code>")
        self.say(chat_id, "\n".join(lines), kb.sub_menu(True))

    # ---------- админ ----------
    def admin_action(self, chat_id: int, user_id: int, action: str) -> None:
        if not self.is_admin(user_id):
            return
        if action == "orders":
            orders = self.db.pending_orders()
            if not orders:
                self.say(chat_id, "Нет заказов, ожидающих выдачи.")
                return
            for order in orders:
                self.say(chat_id,
                         f"#{order['id']} · {order['title']} · {kb.money(order['price'])}\n"
                         f"user {order['user_id']} · {order['status']}",
                         kb.admin_confirm(order["id"]))
        elif action == "stats":
            stats = self.db.stats()
            self.say(chat_id,
                     f"📊 <b>Статистика</b>\n\n"
                     f"Пользователей: {stats['users']}\n"
                     f"Активных подписок: {stats['active_subs']}\n"
                     f"Оплаченных заказов: {stats['paid_orders']}\n"
                     f"Выручка: {kb.money(stats['revenue'])}",
                     kb.back("adm", "← Админ"))
        elif action == "promos":
            lines = ["🏷 <b>Промокоды</b>\n"]
            for p in self.db.promos():
                limit = f"/{p['max_uses']}" if p["max_uses"] else ""
                lines.append(f"<code>{p['code']}</code> · −{p['percent']}% · "
                             f"использован {p['used']}{limit}")
            if len(lines) == 1:
                lines.append("Пока нет.")
            lines.append("\nСоздать: <code>/newpromo КОД ПРОЦЕНТ [ЛИМИТ]</code>\n"
                         "Удалить: <code>/delpromo КОД</code>")
            self.say(chat_id, "\n".join(lines), kb.back("adm", "← Админ"))
        elif action == "reviews":
            st = self.db.review_stats()
            lines = ["⭐ <b>Отзывы</b>\n",
                     f"Средняя оценка: <b>{st['avg']:.1f}</b> из 5 · всего {st['count']}"]
            lines += [f"{kb.stars(n)} — {st['dist'].get(n, 0)}" for n in (5, 4, 3, 2, 1)]
            recent = self.db.recent_reviews(5)
            if recent:
                lines.append("\n<b>Последние:</b>")
                for r in recent:
                    who = f"@{r['username']}" if r.get("username") else f"id {r['user_id']}"
                    lines.append(f"\n{kb.stars(r['rating'])} {html.escape(who)}\n"
                                 f"{html.escape(r['text'][:300])}")
            self.say(chat_id, "\n".join(lines), kb.back("adm", "← Админ"))
        elif action == "keys":
            pool = self.db.pool()
            lines = [f"🔑 <b>Ключи</b> (всего {len(pool)})\n"]
            rows = []
            for k in pool[:10]:
                uuid = server_mod.uuid_from_payload(k["payload"])
                name = k["comment"] or (uuid[:8] if uuid else "ключ")
                mark = " · выдан" if k["used"] else ""
                lines.append(f"#{k['id']} {k['location']} {k['plan_code']} {name}{mark}")
                rows.append([{"text": f"#{k['id']} {name}", "callback_data": f"key:{k['id']}"}])
            rows.append([{"text": "← Админ", "callback_data": "adm"}])
            self.say(chat_id, "\n".join(lines), {"inline_keyboard": rows})
        elif action == "keysync":
            self.sync_keys(chat_id)
        elif action == "sources":
            rows = self.db.stats_by_source()
            lines = ["📈 <b>Источники трафика</b>\n"]
            if not rows:
                lines.append("Пока нет данных — нужны переходы по рекламным ссылкам.")
            for r in rows:
                src = r["source"] or "прямой вход"
                lines.append(f"· {src}: {r['count']}")
            self.say(chat_id, "\n".join(lines), kb.back("adm", "← Админ"))
        elif action == "refs":
            refs = self.db.top_referrers(10)
            lines = ["👥 <b>Топ приглашающих</b>\n"]
            if not refs:
                lines.append("Пока никто не привёл друзей.")
            for r in refs:
                name = r["username"] or f"id{r['id']}"
                lines.append(f"· @{name}: {r['invites']} пригл. · бонус {kb.money(r['balance'])}")
            self.say(chat_id, "\n".join(lines), kb.back("adm", "← Админ"))
        elif action.startswith("key:"):
            key_id = int(action.split(":")[1])
            key = next((k for k in self.db.pool() if k["id"] == key_id), None)
            if key is None:
                return
            uuid = server_mod.uuid_from_payload(key["payload"])
            usage = ""
            panel = self.panels.get(key["location"])
            if uuid and panel:
                try:
                    client = panel.find_by_uuid(uuid)
                    if client:
                        traffic = panel.traffic(client.get("email") or "")
                        used = (traffic.get("up") or 0) + (traffic.get("down") or 0)
                        usage = f"\nИзрасходовано: {server_mod.bytes_to_gb(used)}"
                except Exception:
                    pass
            self.say(chat_id,
                     f"Ключ #{key_id} ({key['plan_code']})\n"
                     f"Имя: {key['comment'] or '—'}{usage}",
                     {"inline_keyboard": [
                         [{"text": "✏️ Имя", "callback_data": f"keyact:{key_id}:rename"},
                          {"text": "📝 Описание", "callback_data": f"keyact:{key_id}:comment"}],
                         [{"text": "← Ключи", "callback_data": "adm:keys"}],
                     ]})
        elif action.startswith("keyact:"):
            _, key_id, act = action.split(":")
            self.awaiting_key[user_id] = {"key_id": int(key_id), "act": act}
            self.say(chat_id, "Пришлите текст одним сообщением.")

    # ---------- обработка ----------
    def sync_keys(self, chat_id: int) -> None:
        """Тянет ссылки со всех панелей и раскладывает по тарифам (m1 → m3 → y1) по кругу."""
        if not self.panels:
            self.say(chat_id, "Панель не подключена — добавьте PANEL_URL в .env.")
            return
        existing = {k["payload"] for k in self.db.pool()}
        codes = [p["code"] for p in config.PLANS]
        added, errors = 0, []
        for loc_code, panel in self.panels.items():
            try:
                links = panel.links()
            except Exception as exc:
                errors.append(f"{config.location(loc_code)['name']}: {exc}")
                continue
            fresh = [l for l in links if l.startswith("vless://") and l not in existing]
            existing.update(fresh)
            for i, code in enumerate(codes):
                chunk = fresh[i::len(codes)]
                if chunk:
                    self.db.add_keys(code, chunk, loc_code)
            added += len(fresh)
        lines = [f"✅ Добавлено ключей с сервера: <b>{added}</b>" if added
                 else "🔄 Всё синхронизировано."]
        for loc in config.LOCATIONS:
            if len(config.LOCATIONS) > 1:
                lines.append(f"\n<b>{loc['name']}</b>")
            else:
                lines.append("")
            lines += [f"· {p['title']}: {self.db.keys_left(p['code'], loc['code'])} шт."
                      for p in config.PLANS]
        if errors:
            lines.append("\n⚠️ Не удалось получить ключи:\n" + "\n".join(errors))
        self.say(chat_id, "\n".join(lines), kb.back("adm", "← Админ"))

    def apply_key_action(self, chat_id: int, task: dict, text: str) -> None:
        key = next((k for k in self.db.pool() if k["id"] == task["key_id"]), None)
        if key is None:
            self.say(chat_id, "Ключ не найден.")
            return
        uuid = server_mod.uuid_from_payload(key["payload"])
        panel = self.panels.get(key["location"])
        if not uuid or not panel:
            self.say(chat_id, "Панель сервера недоступна — действие невозможно.")
            return
        try:
            client = panel.find_by_uuid(uuid)
            if client is None:
                self.say(chat_id, "Клиент не найден на сервере.")
                return
            email = client.get("email") or ""
            if task["act"] == "rename":
                ok = panel.update(email, {"email": text})
                self.db.set_comment(uuid, text)
            else:
                ok = panel.update(email, {"comment": text})
                self.db.set_comment(uuid, text)
            self.say(chat_id, "✅ Готово" if ok else "❌ Не удалось обновить.")
        except Exception as exc:
            self.say(chat_id, f"❌ Ошибка: {exc}")

    def on_message(self, msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        frm = msg.get("from") or {}
        user_id = frm.get("id", chat_id)
        text = (msg.get("text") or "").strip()

        if user_id in self.awaiting_key and text and not text.startswith("/"):
            task = self.awaiting_key.pop(user_id)
            self.apply_key_action(chat_id, task, text)
            return
        if user_id in self.awaiting_review and text and not text.startswith("/"):
            self.save_review_text(chat_id, user_id, frm, text)
            return
        if user_id in self.awaiting_promo and text and not text.startswith("/"):
            self.awaiting_promo.discard(user_id)
            self.apply_promo(chat_id, user_id, text)
            return

        if text.startswith("/start"):
            payload = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            ref_id = None
            source = "direct"
            if payload.startswith("ref_") and payload[4:].isdigit():
                ref_id = int(payload[4:])
                source = "ref"
            elif payload.startswith("src_"):
                source = "src_" + payload[4:]
            elif payload.startswith("promo_"):
                source = "promo_" + self.norm_code(payload[6:])
            self.welcome(chat_id, user_id, frm.get("username", ""), ref_id, source)
            if payload.startswith("promo_"):
                self.apply_promo(chat_id, user_id, payload[6:])
        elif text.startswith(("/newpromo", "/delpromo")) and self.is_admin(user_id):
            self.admin_promo(chat_id, text)
        elif text.startswith("/id"):
            self.say(chat_id, f"Ваш Telegram ID: <code>{user_id}</code>")
        elif text.startswith("/version"):
            self.say(chat_id, f"⚙️ Версия бота: <b>{config.VERSION}</b>")
        elif text.startswith("/help"):
            self.say(chat_id, kb.HELP.format(brand=config.BRAND))
        elif text.startswith("/my"):
            self.show_sub(chat_id, user_id)

    def on_callback(self, query: dict) -> None:
        data = query.get("data") or ""
        chat_id = query["message"]["chat"]["id"]
        frm = query.get("from") or {}
        user_id = frm["id"]
        self.tg.call("answerCallbackQuery", callback_query_id=query["id"])

        if data == "menu":
            self.say(chat_id, "🏠 <b>Главное меню</b>", self.menu(user_id))
        elif data == "plans":
            self.show_plans(chat_id, user_id)
        elif data.startswith("plan:"):
            self.show_plan(chat_id, data[5:], user_id)
        elif data.startswith("buy:"):
            plan_code, _, location = data[4:].partition(":")
            self.start_purchase(chat_id, user_id, plan_code, location)
        elif data.startswith("paid:"):
            self.mark_paid(chat_id, user_id, int(data[5:]))
        elif data.startswith("cancel:"):
            self.cancel_order(chat_id, user_id, int(data[7:]))
        elif data == "my":
            self.show_sub(chat_id, user_id)
        elif data == "trial":
            self.start_trial(chat_id, user_id, frm)
        elif data == "promo":
            self.awaiting_promo.add(user_id)
            self.say(chat_id, "🏷 Отправьте промокод одним сообщением.",
                     kb.back("plans", "← Тарифы"))
        elif data == "help":
            self.say(chat_id, kb.HELP.format(brand=config.BRAND))
        elif data == "support":
            self.say(chat_id, f"💬 <b>Поддержка</b>\n\nПишите: {config.SUPPORT}\n\n"
                              f"Опишите проблему и приложите скриншот — так поможем быстрее.",
                     kb.back("menu", "🏠 Меню"))
        elif data == "invite":
            link = f"https://t.me/{config.BOT_USER}?start=ref_{user_id}"
            share = "https://t.me/share/url?" + urllib.parse.urlencode(
                {"url": link, "text": f"Пользуюсь {config.BRAND} — быстрый VPN без логов"})
            self.say(chat_id,
                     f"🎁 <b>Бонусы за друзей</b>\n\n"
                     f"За каждую покупку друга по вашей ссылке вы получаете "
                     f"<b>{config.REF_PERCENT}%</b> от суммы на бонусный баланс. "
                     f"Бонусы списываются при следующей оплате.\n\n"
                     f"🔗 Ваша ссылка:\n<code>{link}</code>",
                     {"inline_keyboard": [
                         [{"text": "📤 Поделиться ссылкой", "url": share}],
                         [{"text": "🏠 Меню", "callback_data": "menu"}],
                     ]})
        elif data.startswith("card:"):
            self.cmd_card_payment(chat_id, user_id, int(data[5:]))
        elif data.startswith("lava:"):
            self.cmd_lava_payment(chat_id, user_id, int(data[5:]))
        elif data.startswith("enot:"):
            self.cmd_enot_payment(chat_id, user_id, int(data[5:]))
        elif data.startswith("checkpay:"):
            self.check_card_payment(chat_id, int(data[9:]))
        elif data.startswith("rate:") and data[5:].isdigit():
            self.rate(chat_id, user_id, frm, int(data[5:]))
        elif data.startswith("revpub:") and data[7:].isdigit():
            self.publish_review(chat_id, user_id, int(data[7:]))
        elif data == "adm":
            if self.is_admin(user_id):
                self.say(chat_id, "⚙️ Админ-панель", kb.admin_panel())
        elif data.startswith("adm:"):
            self.admin_action(chat_id, user_id, data[4:])
        elif data.startswith("key:"):
            self.admin_action(chat_id, user_id, data[4:])
        elif data.startswith("ok:"):
            self.deliver(int(data[3:]))
            self.say(chat_id, "✅ Ключ выдан покупателю.")
        elif data.startswith("no:"):
            order_id = int(data[3:])
            order = self.db.order(order_id)
            if order:
                self.db.set_status(order_id, "rejected")
                self.say(order["user_id"],
                         "❌ Не нашли ваш платёж. Если вы уже оплатили — напишите в "
                         f"поддержку {config.SUPPORT}, разберёмся.")
            self.say(chat_id, "Отклонено.")

        # старое сообщение с кнопкой удаляем — остаётся только новое
        try:
            self.tg.call("deleteMessage", chat_id=chat_id,
                         message_id=query["message"]["message_id"])
        except Exception:
            pass

    def background_tasks(self) -> None:
        now = time.time()
        # проверка карточных платежей
        if (config.YOOKASSA_SECRET or config.LAVA_SECRET or config.ENOT_API_KEY) \
                and now - self._last_card_check >= 30:
            self._last_card_check = now
            for order in self.db.card_pending_orders():
                try:
                    charge = order["charge_id"]
                    if charge.startswith("enot:"):
                        st = pay_mod.enot_status(config.ENOT_API_KEY, config.ENOT_SHOP_ID,
                                                 str(order["id"]))
                        if st == "paid":
                            self.db.set_status(order["id"], "awaiting")
                            self.deliver(order["id"])
                        elif st in ("expired", "fail", "rejected"):
                            self.db.set_status(order["id"], "new")
                    elif charge == "lava":
                        st = pay_mod.lava_status(config.LAVA_SHOP_ID, config.LAVA_SECRET,
                                                 order["id"])
                        if st == "success":
                            self.db.set_status(order["id"], "awaiting")
                            self.deliver(order["id"])
                        elif st == "fail":
                            self.db.set_status(order["id"], "new")
                    else:
                        payment = pay_mod.get_payment(
                            config.YOOKASSA_SHOP_ID, config.YOOKASSA_SECRET,
                            charge[3:] if charge.startswith("yk:") else charge)
                        status = pay_mod.status(payment)
                        if status == "succeeded":
                            self.db.set_status(order["id"], "awaiting")
                            self.deliver(order["id"])
                        elif status == "canceled":
                            self.db.set_status(order["id"], "new")
                except Exception as exc:
                    print("card check:", exc)
        # здоровье панелей и остаток ключей
        if now - self._last_health >= 600:
            self._last_health = now
            self.check_health()
        # напоминания об окончании подписки и просьбы об отзыве
        if now - self._last_remind >= 3600:
            self._last_remind = now
            self.send_reminders()
            self.send_review_requests()
            self.send_winbacks()

    def send_reminders(self) -> None:
        today = time.strftime("%Y-%m-%d")
        for sub in self.db.expiring_subs(config.REMIND_DAYS):
            if sub.get("reminded_day") == today:
                continue
            days_left = (sub["expires_at"] - int(time.time())) // 86400 + 1
            try:
                self.say(sub["user_id"],
                         f"⏳ <b>Подписка заканчивается через {days_left} дн.</b>\n\n"
                         f"Продлите заранее, чтобы VPN не отключился в самый нужный момент.",
                         kb.back("plans", "🔄 Продлить"))
                self.db.set_reminded(sub["user_id"], today)
            except Exception as exc:
                print("reminder:", exc)

    # ---------- алерты админу ----------
    def check_panel(self, loc: dict) -> str:
        """Пустая строка, если панель отвечает; иначе текст ошибки. Перелогинивается при сбое."""
        panel = self.panels.get(loc["code"])
        if panel:
            try:
                panel.list_clients()
                return ""
            except Exception:
                pass
        try:
            panel = server_mod.Panel(loc["url"], loc["user"], loc["pass"])
            panel.list_clients()
            self.panels[loc["code"]] = panel
            return ""
        except Exception as exc:
            return str(exc)[:200] or exc.__class__.__name__

    def check_health(self) -> None:
        active: dict[str, str] = {}
        for loc in config.LOCATIONS:
            if loc["url"]:
                error = self.check_panel(loc)
                if error:
                    active[f"panel:{loc['code']}"] = (
                        f"🔴 Панель {loc['name']} не отвечает: {html.escape(error)}")
            for plan in config.PLANS:
                left = self.db.keys_left(plan["code"], loc["code"])
                if left <= config.LOW_KEYS:
                    active[f"keys:{loc['code']}:{plan['code']}"] = (
                        f"🔑 {loc['name']} · {plan['title']}: осталось ключей — <b>{left}</b>")
        new_keys = [k for k in active if k not in self._alerts]
        new = [active[k] for k in new_keys]
        fixed = [k for k in self._alerts if k not in active]
        self._alerts = set(active)
        lines = []
        if new:
            lines.append("⚠️ <b>Требует внимания</b>\n\n" + "\n".join(new))
            if any(k.startswith("keys:") for k in new_keys):
                lines.append("\nДобавьте клиентов в панели и нажмите «🔄 Синхронизировать ключи».")
        if fixed:
            lines.append(("\n" if lines else "") + f"✅ Решено проблем: {len(fixed)}")
        if lines:
            self.notify_admins("\n".join(lines), kb.back("adm", "⚙️ Админ-панель"))

    # ---------- отзывы ----------
    def send_review_requests(self) -> None:
        if config.REVIEW_AFTER_DAYS <= 0:
            return
        for uid in self.db.review_candidates(config.REVIEW_AFTER_DAYS):
            self.db.set_review_asked(uid)
            try:
                self.say(uid,
                         f"⭐ <b>Как вам {config.BRAND}?</b>\n\n"
                         f"Вы с нами уже несколько дней. Оцените VPN — это одно нажатие, "
                         f"а нам очень поможет стать лучше.",
                         kb.review_stars())
            except Exception as exc:
                print("review request:", exc)

    def notify_admins(self, text: str, markup: dict | None = None) -> None:
        for admin in self.admins:
            try:
                self.say(admin, text, markup)
            except Exception as exc:
                print("notify admin:", exc)

    @staticmethod
    def who(user_id: int, frm: dict) -> str:
        name = html.escape(frm.get("username") or frm.get("first_name") or "")
        return f"{'@' if frm.get('username') else ''}{name} (<code>{user_id}</code>)".strip()

    def rate(self, chat_id: int, user_id: int, frm: dict, rating: int) -> None:
        rating = max(1, min(5, rating))
        review_id = self.db.add_review(user_id, rating)
        self.awaiting_review[user_id] = review_id
        if rating >= 4:
            text = ("🙏 <b>Спасибо за оценку!</b>\n\n"
                    "Напишите пару слов — что понравилось? Лучшие отзывы мы публикуем.")
        else:
            text = ("😔 <b>Жаль, что не всё понравилось.</b>\n\n"
                    "Напишите, что пошло не так, — передадим в поддержку и поможем разобраться.")
        self.say(chat_id, text, kb.back("menu", "Пропустить"))
        self.notify_admins(f"⭐ <b>Новая оценка</b> {kb.stars(rating)}\n\n"
                           f"От: {self.who(user_id, frm)}")

    def save_review_text(self, chat_id: int, user_id: int, frm: dict, text: str) -> None:
        review_id = self.awaiting_review.pop(user_id)
        review = self.db.review(review_id)
        if not review:
            return
        text = text[:1000]
        self.db.set_review_text(review_id, text)
        if review["rating"] >= 4:
            self.say(chat_id, "💙 Спасибо! Нам очень приятно.", self.menu(user_id))
        else:
            self.say(chat_id, f"Спасибо, что написали. Поддержка уже в курсе и свяжется с вами. "
                              f"Если срочно — {config.SUPPORT}",
                     self.menu(user_id))
        markup = None
        if config.REVIEWS_CHANNEL and review["rating"] >= 4:
            markup = {"inline_keyboard": [[{"text": "📢 Опубликовать в канал",
                                            "callback_data": f"revpub:{review_id}"}]]}
        self.notify_admins(f"💬 <b>Отзыв</b> {kb.stars(review['rating'])}\n\n"
                           f"От: {self.who(user_id, frm)}\n\n{html.escape(text)}", markup)

    def publish_review(self, chat_id: int, user_id: int, review_id: int) -> None:
        if not self.is_admin(user_id):
            return
        review = self.db.review(review_id)
        if not review or not review["text"] or not config.REVIEWS_CHANNEL:
            self.say(chat_id, "Отзыв не найден или канал не настроен (REVIEWS_CHANNEL).")
            return
        if review["published"]:
            self.say(chat_id, "Этот отзыв уже опубликован.")
            return
        try:
            self.say(config.REVIEWS_CHANNEL,
                     f"{kb.stars(review['rating'])}\n\n"
                     f"«{html.escape(review['text'])}»\n\n"
                     f"— клиент {config.BRAND}\n\n"
                     f"🛡 Подключить: https://t.me/{config.BOT_USER}?start=src_reviews")
            self.db.set_review_published(review_id)
            self.say(chat_id, "✅ Опубликовано в канале.")
        except Exception as exc:
            self.say(chat_id, f"❌ Не удалось опубликовать: {exc}\n"
                              f"Проверьте, что бот — админ канала {config.REVIEWS_CHANNEL}.")

    def poll(self) -> None:
        while True:
            try:
                result = self.tg.call("getUpdates", offset=self.offset, timeout=25,
                                      allowed_updates=["message", "callback_query"])
                for update in result.get("result", []):
                    self.offset = update["update_id"] + 1
                    if "message" in update:
                        self.on_message(update["message"])
                    elif "callback_query" in update:
                        self.on_callback(update["callback_query"])
                self.background_tasks()
            except Exception as exc:
                print("ошибка опроса:", exc)
                time.sleep(5)


# ---------------------------------------------------------------- selftest
class FakeTransport:
    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, method, params, files):
        self.calls.append((method, params, files))
        return {"ok": True, "result": {"message_id": len(self.calls)}}

    def count(self, method: str) -> int:
        return sum(1 for c in self.calls if c[0] == method)


def selftest() -> int:
    import tempfile

    ok = True

    def check(name: str, cond: bool) -> None:
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        ok = ok and cond

    tmp = Path(tempfile.mkdtemp()) / "test.db"
    db = Storage(tmp)
    t = FakeTransport()
    bot = VpnBot(Telegram("test", transport=t), db, {1})

    print("1. Приветствие")
    bot.welcome(42, 42, "user42")
    check("баннер/приветствие отправлено", t.count("sendPhoto") >= 1 or t.count("sendMessage") >= 1)

    print("2. Тарифы")
    bot.show_plans(42)
    check("тарифы меню", t.count("sendMessage") >= 1)
    bot.show_plan(42, "m1")
    check("карточка с фото", t.count("sendPhoto") >= 1)

    print("3. Покупка")
    bot.start_purchase(42, 42, "m1")
    check("создан заказ #1", db.recent_orders(1)[0]["id"] == 1)
    check("показаны реквизиты", "СБП" in t.calls[-1][1]["text"])

    print("4. Оплата и выдача")
    db.add_keys("m1", ["vless://test-key-1"])
    bot.mark_paid(42, 42, 1)
    check("заявка ушла админу", db.order(1)["status"] == "awaiting")
    bot.deliver(1)
    check("ключ выдан", db.order(1)["status"] == "paid")
    check("подписка создана", db.sub(42).get("payload") == "vless://test-key-1")
    check("ключ потрачен", db.keys_left("m1") == 0)

    print("5. Подписка")
    bot.show_sub(42, 42)
    check("ключ в подписке", "vless://test-key-1" in t.calls[-1][1]["text"])

    print("6. Статистика")
    stats = db.stats()
    check("выручка посчитана", stats["revenue"] == config.PLANS[0]["price"]
          and stats["paid_orders"] == 1)

    print("7. Отзывы")
    db.db.execute("UPDATE orders SET created_at = created_at - 10 * 86400")
    bot.send_review_requests()
    check("просьба об оценке отправлена", "rate:5" in json.dumps(t.calls[-1][1]))
    bot.send_review_requests()
    check("повторно не спрашиваем", not db.review_candidates(0))
    bot.on_callback({"id": "q", "data": "rate:5", "from": {"id": 42, "username": "user42"},
                     "message": {"chat": {"id": 42}, "message_id": 1}})
    bot.on_message({"chat": {"id": 42}, "from": {"id": 42, "username": "user42"},
                    "text": "Летает!"})
    st = db.review_stats()
    check("отзыв сохранён", st["count"] == 1 and db.recent_reviews(1)[0]["text"] == "Летает!")
    bot.admin_action(1, 1, "reviews")
    check("отзывы в админке", "Летает!" in t.calls[-1][1]["text"])

    print("8. Локации")
    config.LOCATIONS.append({"code": "fi", "name": "🇫🇮 Финляндия", "url": "", "user": "", "pass": ""})
    db.add_keys("m3", ["vless://de-key"])
    db.add_keys("m3", ["vless://fi-key"], "fi")
    bot.start_purchase(42, 42, "m3")
    check("предложен выбор страны", "buy:m3:fi" in json.dumps(t.calls[-1][1]))
    bot.on_callback({"id": "q", "data": "buy:m3:fi", "from": {"id": 42},
                     "message": {"chat": {"id": 42}, "message_id": 1}})
    order_id = db.recent_orders(1)[0]["id"]
    check("страна сохранена в заказе", db.order(order_id)["location"] == "fi")
    db.set_status(order_id, "awaiting")
    bot.deliver(order_id)
    check("выдан ключ нужной страны", db.sub(42)["payload"] == "vless://fi-key")
    bot.start_purchase(42, 42, "m3")
    check("одна страна в наличии — без выбора", "СБП" in t.calls[-1][1]["text"])
    config.LOCATIONS.pop()

    print("9. Алерты")
    sent = t.count("sendMessage")
    bot.check_health()
    check("админ узнал, что ключи заканчиваются", t.count("sendMessage") > sent
          and "осталось ключей" in t.calls[-1][1]["text"])
    sent = t.count("sendMessage")
    bot.check_health()
    check("повторно не спамим", t.count("sendMessage") == sent)

    print("10. Пробный период")
    config.TRIAL_DAYS = 1
    revenue = db.stats()["revenue"]
    db.ensure_user(77, "new77")
    check("кнопка пробного у новичка", "trial" in json.dumps(bot.menu(77)))
    check("нет кнопки у покупателя", "trial" not in json.dumps(bot.menu(42)))
    db.add_keys("m1", ["vless://trial-key"])
    bot.on_callback({"id": "q", "data": "trial", "from": {"id": 77, "username": "new77"},
                     "message": {"chat": {"id": 77}, "message_id": 1}})
    check("пробный ключ выдан", db.sub(77).get("payload") == "vless://trial-key"
          and "Пробный период" in t.calls[-2][1]["text"])
    check("второй раз нельзя", not bot.trial_available(77))
    check("пробный не в выручке", db.stats()["revenue"] == revenue)

    print("11. Промокоды")
    bot.on_message({"chat": {"id": 1}, "from": {"id": 1}, "text": "/newpromo boss20 20 1"})
    check("админ создал промокод", db.promo("BOSS20").get("percent") == 20)
    bot.on_message({"chat": {"id": 77}, "from": {"id": 77}, "text": "/start promo_BOSS20"})
    check("применён по ссылке", bot.user_promo(77) == ("BOSS20", 20))
    db.add_keys("m3", ["vless://promo-key"])
    bot.start_purchase(77, 77, "m3")
    order = db.recent_orders(1)[0]
    check("цена со скидкой", order["price"] == kb.discounted(199, 20) and "−20%" in t.calls[-1][1]["text"])
    db.set_status(order["id"], "awaiting")
    bot.deliver(order["id"])
    check("лимит исчерпан", db.promo("BOSS20")["used"] == 1 and bot.user_promo(77)[1] == 0)
    bot.on_callback({"id": "q", "data": "promo", "from": {"id": 42},
                     "message": {"chat": {"id": 42}, "message_id": 1}})
    bot.on_message({"chat": {"id": 42}, "from": {"id": 42}, "text": "boss20"})
    check("закончившийся код не принят", "закончился" in t.calls[-1][1]["text"])

    print("12. Возврат ушедших")
    db.db.execute("UPDATE subs SET expires_at = ? WHERE user_id = 42", (int(time.time()) - 3 * 86400,))
    bot.send_winbacks()
    check("ушедшему пришла скидка", t.calls[-1][1].get("chat_id") == 42
          and bot.user_promo(42)[1] == config.WINBACK_PERCENT)
    sent = t.count("sendMessage")
    bot.send_winbacks()
    check("один раз", t.count("sendMessage") == sent)

    print("\nИтог:", "всё работает" if ok else "есть ошибки")
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        code = selftest()
        os._exit(code)
    if not config.BOT_TOKEN:
        print("Нет BOT_TOKEN. Заполните .env или запустите: python bot.py --selftest")
        return 1
    bot = VpnBot(Telegram(config.BOT_TOKEN), Storage(config.DB_PATH), config.ADMINS)
    bot.setup_profile()
    print(f"{config.BRAND} запущен. Ctrl+C — остановить.")
    bot.poll()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
