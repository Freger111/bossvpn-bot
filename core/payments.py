"""ЮKassa: создание и проверка платежей (Basic Auth, без внешних библиотек)."""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
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
import hashlib
import hmac as _hmac


def _lava_signature(secret: str, data: dict) -> str:
    """HMAC-SHA256 от JSON с отсортированными ключами (как в официальном SDK)."""
    payload = json.dumps(dict(sorted(data.items())), ensure_ascii=False,
                         separators=(",", ":"), sort_keys=True)
    return _hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _lava_post(secret: str, path: str, data: dict) -> dict:
    data["signature"] = _lava_signature(secret, data)
    req = urllib.request.Request(
        LAVA + path,
        data=json.dumps(data, ensure_ascii=False).encode(),
        headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"error": exc.read().decode("utf-8", "replace")[:300]}


def lava_create_invoice(shop_id: str, secret: str, amount_rub: int, order_id: int) -> str:
    """Создаёт счёт в Lava, возвращает ссылку на оплату."""
    data = {"sum": float(amount_rub), "orderId": str(order_id), "shopId": shop_id,
            "expire": 60, "comment": f"БоссVPN заказ #{order_id}"}
    result = _lava_post(secret, "/business/invoice/create", data)
    return ((result.get("data") or {}).get("url")) or ""


def lava_status(shop_id: str, secret: str, order_id: int) -> str:
    """status: success / fail / pending / unknown."""
    result = _lava_post(secret, "/business/invoice/status",
                        {"shopId": shop_id, "orderId": str(order_id)})
    return ((result.get("data") or {}).get("status")) or "unknown"


# ---------------------------------------------------------------- Enot
ENOT = "https://api.enot.io"


def enot_create_invoice(api_key: str, shop_id: str, amount_rub: int, order_id: int) -> str:
    """Создаёт платёж в Enot, возвращает ссылку на оплату."""
    req = urllib.request.Request(
        ENOT + "/invoice/create",
        data=json.dumps({"amount": float(amount_rub), "order_id": str(order_id),
                         "currency": "RUB", "shop_id": shop_id,
                         "comment": f"БоссVPN заказ #{order_id}", "expire": 60}).encode(),
        headers={"Accept": "application/json", "Content-Type": "application/json",
                 "x-api-key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return ""
    return ((data.get("data") or {}).get("url")) or ""


def enot_status(api_key: str, shop_id: str, invoice_id: str) -> str:
    """status: paid / expired / fail / pending / unknown."""
    url = (ENOT + "/invoice/info?" + urllib.parse.urlencode(
        {"invoice_id": invoice_id, "shop_id": shop_id}))
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "x-api-key": api_key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return "unknown"
    return ((data.get("data") or {}).get("status")) or "unknown"
