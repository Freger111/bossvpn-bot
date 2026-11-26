"""VPN-бот: покупка тарифа, оплата, выдача ключа, подписка, админка."""
from __future__ import annotations

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
        self.panel = None
        self._last_card_check = 0.0
        self._last_remind = 0.0
        if config.PANEL_URL:
            try:
                self.panel = server_mod.Panel(config.PANEL_URL, config.PANEL_USER,
                                              config.PANEL_PASS)
            except Exception as exc:
                print("панель недоступна:", exc)

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
        self.send_banner(chat_id, caption, kb.main_menu(self.is_admin(user_id)))

    def show_plans(self, chat_id: int) -> None:
        self.say(chat_id, "🛡 <b>Выберите тариф</b>\n\n"
                          "Чем дольше срок — тем дешевле месяц.\n"
                          "Во всех тарифах: без логов · VLESS · Reality · iOS / Android / Windows",
                 kb.plans())

    def show_plan(self, chat_id: int, plan_code: str) -> None:
        plan = next((p for p in config.PLANS if p["code"] == plan_code), None)
        if plan is None:
            return
        left = self.db.keys_left(plan_code)
        icon = kb.PLAN_ICONS.get(plan_code, "🛡")
        text = (f"{icon} <b>{plan['title']}</b> · {kb.money(plan['price'])}\n\n"
                f"📅 {plan['days']} дней доступа\n"
                f"📦 {plan.get('gb', 0)} ГБ трафика\n"
                f"📱 до {plan.get('devices', 1)} устройств\n"
                f"⚡ VLESS · Reality\n\n"
                f"💡 Выходит ≈ <b>{kb.per_month(plan)} ₽ в месяц</b>")
        if left == 0:
            text += "\n\n⏳ Ключи временно закончились — скоро пополним."
        elif left <= 5:
            text += f"\n\n🔥 Осталось ключей: {left}"
        self.say_photo(chat_id, config.plan_image(plan_code), text,
                       kb.plan_card(plan_code))

    # ---------- покупка ----------
    def start_purchase(self, chat_id: int, user_id: int, plan_code: str) -> None:
        plan = next((p for p in config.PLANS if p["code"] == plan_code), None)
        if plan is None:
            return
        user = self.db.ensure_user(user_id)
        balance = user.get("balance") or 0
        balance_used = min(balance, plan["price"])
        price = plan["price"] - balance_used
        order_id = self.db.create_order(user_id, plan, price=price, balance_used=balance_used)
        if balance_used:
            self.db.add_balance(user_id, -balance_used)
        text = (f"🧾 <b>Заказ #{order_id}</b> · {plan['title']}\n\n"
                f"К оплате: <b>{kb.money(price)}</b>")
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
        if not self.panel:
            return happ, email
        uuid = server_mod.uuid_from_payload(payload)
        if not uuid:
            return happ, email
        try:
            client = self.panel.find_by_uuid(uuid)
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
                                for c in self.panel.list_clients())
                    if taken:
                        new_email += f"-{uuid[:6]}"
                    fields["email"] = new_email
                    email = new_email
                if comment and (client.get("comment") or "") != comment:
                    fields["comment"] = comment
                if len(fields) > 1 or fields.get("email") != client.get("email"):
                    self.panel.update(client.get("email") or "", fields)
                happ = self.panel.happ_link(client["id"])
        except Exception as exc:
            print("sync_server_sub:", exc)
        return happ, email

    def deliver(self, order_id: int) -> None:
        order = self.db.order(order_id)
        if not order or order["status"] != "awaiting":
            return
        key = self.db.take_key(order["plan_code"], order_id)
        if key is None:
            self.say(order["user_id"],
                     "⚠️ Ключи для этого тарифа временно закончились. Оплата сохранена — "
                     f"пришлём ключ в ближайшее время. Вопросы: {config.SUPPORT}")
            return
        self.db.set_status(order_id, "paid")
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
        lines = [f"🎉 <b>Готово! VPN активирован</b>\n\n"
                 f"📦 Тариф: {order['title']}\n"
                 f"📅 Действует до: <b>{time.strftime('%d.%m.%Y', time.localtime(expires))}</b>\n"
                 f"📊 Трафик: <b>{plan.get('gb', 0)} ГБ</b>\n"
                 f"📱 Устройств: <b>{plan.get('devices', 1)}</b>\n\n"
                 f"🔑 <b>Ваш ключ</b> — нажмите, чтобы скопировать:\n"
                 f"<code>{key}</code>"]
        if happ:
            lines.append(f"\n📲 <b>Happ</b> — подключение в один клик, "
                         f"там видна подписка и трафик:\n<code>{happ}</code>")
        lines.append("\nВставьте ключ в приложение — пошаговая инструкция по кнопке ниже.")
        self.say(order["user_id"], "\n".join(lines), kb.back("help", "📱 Как подключить"))

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
        key_uuid = server_mod.uuid_from_payload(sub["payload"])
        if key_uuid and self.panel:
            try:
                client = self.panel.find_by_uuid(key_uuid)
                if client:
                    traffic = self.panel.traffic(client.get("email") or "")
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
        elif action == "keys":
            pool = self.db.pool()
            lines = [f"🔑 <b>Ключи</b> (всего {len(pool)})\n"]
            rows = []
            for k in pool[:10]:
                uuid = server_mod.uuid_from_payload(k["payload"])
                name = k["comment"] or (uuid[:8] if uuid else "ключ")
                mark = " · выдан" if k["used"] else ""
                lines.append(f"#{k['id']} {k['plan_code']} {name}{mark}")
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
            if uuid and self.panel:
                try:
                    client = self.panel.find_by_uuid(uuid)
                    if client:
                        traffic = self.panel.traffic(client.get("email") or "")
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
        """Тянет все ссылки с панели и раскладывает по тарифам (m1 → m3 → y1)."""
        if not self.panel:
            self.say(chat_id, "Панель не подключена — добавьте PANEL_URL в .env.")
            return
        try:
            links = self.panel.links()
        except Exception as exc:
            self.say(chat_id, f"Не удалось получить ключи с сервера: {exc}")
            return
        existing = {k["payload"] for k in self.db.pool()}
        fresh = [l for l in links if l.startswith("vless://") and l not in existing]
        if not fresh:
            left = {p["code"]: self.db.keys_left(p["code"]) for p in config.PLANS}
            self.say(chat_id,
                     "🔄 Всё синхронизировано.\n\n" +
                     "\n".join(f"· {config.PLANS[i]['title']}: {left[p['code']]} шт."
                               for i, p in enumerate(config.PLANS)),
                     kb.back("adm", "← Админ"))
            return
        # все новые ссылки раскладываем по тарифам по кругу
        pools: dict[str, list[str]] = {p["code"]: [] for p in config.PLANS}
        codes = list(pools)
        for i, link in enumerate(fresh):
            pools[codes[i % len(codes)]].append(link)
        for code in pools:
            if pools[code]:
                self.db.add_keys(code, pools[code])
        left = {p["code"]: self.db.keys_left(p["code"]) for p in config.PLANS}
        self.say(chat_id,
                 f"✅ Добавлено ключей с сервера: <b>{len(fresh)}</b>\n\n" +
                 "\n".join(f"· {config.PLANS[i]['title']}: {left[p['code']]} шт."
                           for i, p in enumerate(config.PLANS)),
                 kb.back("adm", "← Админ"))

    def apply_key_action(self, chat_id: int, task: dict, text: str) -> None:
        key = next((k for k in self.db.pool() if k["id"] == task["key_id"]), None)
        if key is None:
            self.say(chat_id, "Ключ не найден.")
            return
        uuid = server_mod.uuid_from_payload(key["payload"])
        if not uuid or not self.panel:
            self.say(chat_id, "Панель сервера недоступна — действие невозможно.")
            return
        try:
            client = self.panel.find_by_uuid(uuid)
            if client is None:
                self.say(chat_id, "Клиент не найден на сервере.")
                return
            email = client.get("email") or ""
            if task["act"] == "rename":
                ok = self.panel.update(email, {"email": text})
                self.db.set_comment(uuid, text)
            else:
                ok = self.panel.update(email, {"comment": text})
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

        if text.startswith("/start"):
            payload = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            ref_id = None
            source = "direct"
            if payload.startswith("ref_") and payload[4:].isdigit():
                ref_id = int(payload[4:])
                source = "ref"
            elif payload.startswith("src_"):
                source = "src_" + payload[4:]
            self.welcome(chat_id, user_id, frm.get("username", ""), ref_id, source)
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
        user_id = query["from"]["id"]
        self.tg.call("answerCallbackQuery", callback_query_id=query["id"])

        if data == "menu":
            self.say(chat_id, "🏠 <b>Главное меню</b>", kb.main_menu(self.is_admin(user_id)))
        elif data == "plans":
            self.show_plans(chat_id)
        elif data.startswith("plan:"):
            self.show_plan(chat_id, data[5:])
        elif data.startswith("buy:"):
            self.start_purchase(chat_id, user_id, data[4:])
        elif data.startswith("paid:"):
            self.mark_paid(chat_id, user_id, int(data[5:]))
        elif data.startswith("cancel:"):
            self.cancel_order(chat_id, user_id, int(data[7:]))
        elif data == "my":
            self.show_sub(chat_id, user_id)
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
        # напоминания об окончании подписки
        if now - self._last_remind >= 3600:
            self._last_remind = now
            self.send_reminders()

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
