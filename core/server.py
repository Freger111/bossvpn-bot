"""Клиент панели 3x-ui: трафик, переименование, комментарии, создание клиентов."""
from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.error
import urllib.request

CSRF_RE = re.compile(r'csrf-token"\s+content="([^"]+)"')


class Panel:
    def __init__(self, base_url: str, username: str, password: str):
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self._csrf = ""
        self._login()

    def _request(self, method: str, path: str, data: dict | None = None) -> dict:
        url = self.base + path
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json",
                   "X-CSRF-Token": self._csrf}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method=method)
        with self.opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _login(self) -> None:
        with self.opener.open(self.base + "/", timeout=30) as resp:
            page = resp.read().decode("utf-8", "replace")
        match = CSRF_RE.search(page)
        self._csrf = match.group(1) if match else ""
        result = self._request("POST", "/login",
                               {"username": self.username, "password": self.password})
        if not result.get("success"):
            raise RuntimeError(f"не удалось войти в панель: {result.get('msg')}")

    def _refresh_if_needed(self, result: dict) -> dict:
        return result

    def list_clients(self) -> list[dict]:
        result = self._request("GET", "/panel/api/clients/list")
        return result.get("obj") or []

    def traffic(self, email: str) -> dict:
        result = self._request("GET", f"/panel/api/clients/traffic/{email}")
        return result.get("obj") or {}

    def get(self, email: str) -> dict:
        result = self._request("GET", f"/panel/api/clients/get/{email}")
        obj = result.get("obj") or {}
        return obj.get("client") or obj

    def update(self, email: str, fields: dict) -> bool:
        result = self._request("POST", f"/panel/api/clients/update/{email}", fields)
        return bool(result.get("success"))

    def create(self, email: str, inbound_ids: list[int]) -> bool:
        result = self._request("POST", "/panel/api/clients/add",
                               {"client": {"email": email, "flow": "xtls-rprx-vision",
                                           "enable": True},
                                "inboundIds": inbound_ids})
        return bool(result.get("success"))

    def links(self) -> list[str]:
        result = self._request("GET", "/panel/api/inbounds/allLinks")
        return result.get("obj") or []

    def find_by_uuid(self, uuid: str) -> dict | None:
        for client in self.list_clients():
            if client.get("uuid") == uuid:
                return client
        return None


def uuid_from_payload(payload: str) -> str:
    match = re.search(r"vless://([0-9a-fA-F-]{36})@", payload)
    return match.group(1) if match else ""


def bytes_to_gb(value: int) -> str:
    return f"{value / 1024 ** 3:.2f} ГБ" if value else "0 ГБ"
