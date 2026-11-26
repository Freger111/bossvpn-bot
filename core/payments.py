"""ЮKassa: создание и проверка платежей (Basic Auth, без внешних библиотек)."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
import uuid

API = "https://api.yookassa.ru/v3"


def _auth_header(shop_id: str, secret: str) -> str:
    raw = f"{shop_id}:{secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _call(shop_id: str, secret: str, method: str, path: str,
          data: dict | None = None) -> dict:
    url = API + path
    headers = {"Authorization": _auth_header(shop_id, secret),
               "Content-Type": "application/json",
               "Idempotence-Key": uuid.uuid4().hex}
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(detail)
        except Exception:
            return {"error": detail[:300]}


def create_payment(shop_id: str, secret: str, amount_rub: int, description: str,
                   order_id: int) -> dict:
    """Создаёт платёж, возвращает {id, confirmation_url}."""
    result = _call(shop_id, secret, "POST", "/payments", {
        "amount": {"value": f"{amount_rub}.00", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": "https://t.me/bossvphbot"},
        "description": description[:128],
        "metadata": {"order_id": order_id},
    })
    return result


def get_payment(shop_id: str, secret: str, payment_id: str) -> dict:
    return _call(shop_id, secret, "GET", f"/payments/{payment_id}")


def status(payment: dict) -> str:
    return payment.get("status", "unknown")


# ---------------------------------------------------------------- Lava
LAVA = "https://api.lava.ru"


def lava_create_invoice(shop_id: str, secret: str, amount_rub: int, order_id: int) -> str:
    """Создаёт счёт в Lava, возвращает ссылку на оплату."""
    req = urllib.request.Request(
        LAVA + "/business/invoice/create",
        data=json.dumps({"sum": float(amount_rub), "orderId": str(order_id),
                         "shopId": shop_id, "expire": 60,
                         "comment": f"БоссVPN заказ #{order_id}"}).encode(),
        headers={"Authorization": secret, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return ""
    return ((data.get("data") or {}).get("url")) or ""


def lava_status(shop_id: str, secret: str, order_id: int) -> str:
    """status: success / pending / fail / None."""
    req = urllib.request.Request(
        LAVA + "/business/invoice/status",
        data=json.dumps({"shopId": shop_id, "orderId": str(order_id)}).encode(),
        headers={"Authorization": secret, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return "unknown"
    return ((data.get("data") or {}).get("status")) or "unknown"
