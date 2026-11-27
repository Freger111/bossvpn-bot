"""HTTP-прокси подписок: отдаёт sub-контент панели 3x-ui через домен бота.

Позволяет раздавать подписки по https://<домен-бота>/sub/<subId> —
нужен, когда порт панели подписок недоступен у клиентов.
"""
from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import config

HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate",
               "proxy-authorization", "te", "trailers",
               "transfer-encoding", "upgrade", "host", "content-length"}


class SubProxy(BaseHTTPRequestHandler):
    server_version = "SubProxy/1.0"

    def _proxy(self) -> None:
        parts = urlsplit(self.path)
        if parts.path != "/healthz" and not parts.path.startswith("/sub/"):
            self.send_error(404, "not found")
            return
        if parts.path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        subid = parts.path[len("/sub/"):].strip("/")
        if not subid or "/" in subid:
            self.send_error(404, "not found")
            return
        upstream = config.SUB_UPSTREAM.rstrip("/") + "/" + subid + ("?" + parts.query if parts.query else "")

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_HEADERS}
        req = urllib.request.Request(upstream, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    if key.lower() not in HOP_HEADERS:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except urllib.error.HTTPError as exc:
            body = exc.read() or b""
            self.send_response(exc.code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = f"upstream error: {exc}".encode()
            self.send_response(502)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    do_GET = _proxy
    do_HEAD = _proxy

    def log_message(self, fmt, *args) -> None:  # тихие логи
        pass


def serve() -> None:
    port = config.SUB_PORT
    if not port:
        return
    server = ThreadingHTTPServer(("0.0.0.0", port), SubProxy)
    print(f"sub-proxy: http://0.0.0.0:{port}/sub/<subId>")
    server.serve_forever()


def start() -> None:
    if not config.SUB_PORT:
        return
    threading.Thread(target=serve, daemon=True).start()
